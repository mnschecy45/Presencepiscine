import streamlit as st
import pandas as pd
import pdfplumber
import re
import io
from datetime import datetime, date
from pyairtable import Api  # <--- On remplace GSheets par Airtable

# =======================
# 0. TES CLES AIRTABLE (A REMPLIR ICI)
# =======================
API_TOKEN = "pat85co2rWjG48EDz.e6e628e1b5da543271388625e0006a0186a2e424ff7a3ae6e146508794f8edbd" # Ton token
BASE_ID = "app390ytx6oa2rbge"    # Ton ID de base
TABLE_NAME = "Presences"             # Nom de l'onglet

# =======================
# 1. CONFIGURATION GÉNÉRALE
# =======================
st.set_page_config(page_title="Piscine Pro - Gestion Cloud", layout="wide", page_icon="🏊‍♂️")

MANAGER_PASSWORD = st.secrets.get("MANAGER_PASSWORD", "manager")

# --- CONNEXION AIRTABLE ---
# --- CONNEXION AIRTABLE ET CHARGEMENT ---
try:
    api = Api(API_TOKEN)
    table = api.table(BASE_ID, TABLE_NAME)
    
    # On récupère TOUT (y compris les ID secrets des lignes)
    records = table.all()
    
    if records:
        data = []
        for r in records:
            row = r['fields']
            row['id'] = r['id']  # <--- C'est ça la clé magique pour modifier ensuite !
            data.append(row)
        df_all = pd.DataFrame(data)
        
        # Nettoyage des dates
        if "Date" in df_all.columns:
            df_all["Date_dt"] = pd.to_datetime(df_all["Date"], errors='coerce')
    else:
        df_all = pd.DataFrame()
except Exception as e:
    st.error(f"Erreur de connexion Airtable : {e}")
    df_all = pd.DataFrame()

# =======================
# 2. LOGIQUE DE SAUVEGARDE & PDF
# =======================
def save_data_to_cloud(df_new):
    """
    Envoie les nouvelles lignes vers Airtable une par une.
    """
    progress_bar = st.progress(0)
    total = len(df_new)
    
    for i, row in df_new.iterrows():
        try:
            # On prépare la ligne pour Airtable
            statut_final = "Absent" if row["Absent"] else "Présent"
            
            # Conversion de la date pour Airtable
            if isinstance(row["Date"], (date, datetime)):
                date_str = row["Date"].strftime("%Y-%m-%d")
            else:
                date_str = str(row["Date"])

            # --- C'EST ICI QUE CA SE JOUE ---
            record = {
                "Nom": row["Nom"],
                "Statut": statut_final, 
                "Date": date_str,
                "Cours": row["Cours"],  # <--- J'ai enlevé le # devant
                "Heure": row["Heure"]   # <--- J'ai enlevé le # devant
            }
            
            # Envoi vers Airtable
            table.create(record)
            
            # Mise à jour barre de progression
            progress_bar.progress((i + 1) / total)
            
        except Exception as e:
            st.error(f"Erreur lors de l'enregistrement de {row['Nom']}: {e}")

    progress_bar.empty()
    st.toast("Enregistrement Airtable terminé !", icon="☁️")

def parse_pdf_complete(file_bytes):
    rows = []
    ignore_list = ["TCPDF", "www.", "places", "réservées", "disponibles", "ouvertes", "le ", " à ", "Page ", "Généré"]
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for idx, page in enumerate(pdf.pages):
                txt = page.extract_text()
                if not txt: continue
                lines = txt.splitlines()
                d_str = ""
                for l in lines[:15]:
                    m = re.search(r"\d{2}/\d{2}/\d{4}", l)
                    if m: d_str = m.group(0); break
                s_date = datetime.strptime(d_str, "%d/%m/%Y").date() if d_str else date.today()
                c_name, h_deb = "Cours Inconnu", "00h00"
                for l in lines[:15]:
                    ts = re.findall(r"\d{1,2}h\d{2}", l)
                    if ts:
                        h_deb = ts[0]
                        c_name = l[:l.index(ts[0])].strip()
                        break
                start_index = 0
                for i, l in enumerate(lines):
                    if "N° réservation" in l:
                        start_index = i + 1
                        break
                for l in lines[start_index:]:
                    if not l.strip() or any(x in l for x in ignore_list):
                        continue
                    l_clean = re.sub(r'\d+', '', l).strip()
                    l_clean = re.sub(r'\s+', ' ', l_clean)
                    parts = l_clean.split()
                    if len(parts) >= 2:
                        rows.append({
                            "Date": s_date, "Cours": c_name, "Heure": h_deb,
                            "Nom": parts[0].upper(), "Prenom": " ".join(parts[1:]),
                            "Absent": False, "Manuel": False, "Session_ID": f"{s_date}_{h_deb}"
                        })
    except: pass
    return pd.DataFrame(rows)

# =======================
# 3. INTERFACE MAÎTRE-NAGEUR
# =======================
def show_maitre_nageur():
    st.markdown("<div id='top'></div>", unsafe_allow_html=True)
    st.title("👨‍🏫 Appel Bassin")
    
    if st.session_state.get("appel_termine", False):
        st.success("✅ Appel enregistré dans Airtable !")
        if st.button("Faire un nouvel appel"):
            # On nettoie tout pour le nouvel appel
            for key in list(st.session_state.keys()):
                if key.startswith("cb_") or key == "df_appel":
                    del st.session_state[key]
            st.session_state.appel_termine = False
            st.rerun()
        return

    up = st.file_uploader("Charger le PDF d'appel", type=["pdf"])
    
    # Si on charge un nouveau fichier, on nettoie les anciennes cases
    if up:
        if 'current_file' not in st.session_state or st.session_state.current_file != up.name:
            st.session_state.current_file = up.name
            for key in list(st.session_state.keys()):
                if key.startswith("cb_"):
                    del st.session_state[key]
            st.session_state.df_appel = parse_pdf_complete(up.read())

        df = st.session_state.df_appel
        
        # Affichage Jour + Date
        if not df.empty:
            d_obj = df['Date'].iloc[0]
            jours_fr = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
            # Gestion sécurité si d_obj n'est pas une date
            if isinstance(d_obj, (date, datetime)):
                date_complete = f"{jours_fr[d_obj.weekday()]} {d_obj.strftime('%d/%m/%Y')}"
            else:
                date_complete = str(d_obj)

            st.info(f"📅 **{date_complete}** | {df['Cours'].iloc[0]} à {df['Heure'].iloc[0]}")

            # --- ACTIONS RAPIDES ---
            c1, c2, c3 = st.columns([1, 1, 1])
            if c1.button("✅ TOUT PRÉSENT", use_container_width=True):
                for i in range(len(df)):
                    st.session_state[f"cb_{i}"] = True
                st.rerun()
                
            if c2.button("❌ TOUT ABSENT", use_container_width=True):
                for i in range(len(df)):
                    st.session_state[f"cb_{i}"] = False
                st.rerun()
                
            c3.markdown("<p style='text-align:center;'><a href='#bottom'>⬇️ Aller au résumé</a></p>", unsafe_allow_html=True)

            st.write("---")

            # --- LISTE DES ÉLÈVES ---
            for idx, row in df.iterrows():
                key = f"cb_{idx}"
                # Initialisation par défaut si la clé n'existe pas
                if key not in st.session_state:
                    st.session_state[key] = False
                
                # La couleur suit strictement l'état de la session_state
                bg = "#dcfce7" if st.session_state[key] else "#fee2e2"
                
                col_n, col_c = st.columns([4, 1])
                col_n.markdown(f"""
                    <div style='padding:12px; background:{bg}; color:black; border-radius:8px; margin-bottom:5px; border:1px solid #ccc;'>
                        <strong>{row['Nom']} {row['Prenom']}</strong>
                    </div>
                """, unsafe_allow_html=True)
                
                # Utilisation du paramètre 'value' pour forcer l'affichage synchronisé
                st.checkbox("P", key=key, label_visibility="collapsed")
                df.at[idx, "Absent"] = not st.session_state[key]

            # Ajout manuel
            st.write("---")
            with st.expander("➕ AJOUTER UN ÉLÈVE HORS PDF"):
                with st.form("form_ajout", clear_on_submit=True):
                    nom_m = st.text_input("Nom").upper()
                    prenom_m = st.text_input("Prénom")
                    if st.form_submit_button("Valider"):
                        if nom_m and prenom_m:
                            nouveau = {
                                "Date": df['Date'].iloc[0], "Cours": df['Cours'].iloc[0], "Heure": df['Heure'].iloc[0],
                                "Nom": nom_m, "Prenom": prenom_m, "Absent": False, "Manuel": True, "Session_ID": df['Session_ID'].iloc[0]
                            }
                            st.session_state.df_appel = pd.concat([df, pd.DataFrame([nouveau])], ignore_index=True)
                            st.rerun()

            st.markdown("<div id='bottom'></div>", unsafe_allow_html=True)
            st.write("---")
            
            # Résumé
            presents = len(df[df["Absent"] == False])
            st.subheader("📋 Résumé")
            r1, r2, r3 = st.columns(3)
            r1.metric("Inscrits", len(df[df["Manuel"]==False]))
            r2.metric("Absents", len(df[df["Absent"]==True]), delta_color="inverse")
            r3.metric("DANS L'EAU", presents)

            if st.button("💾 ENREGISTRER DÉFINITIVEMENT", type="primary", use_container_width=True):
                save_data_to_cloud(df)
                st.session_state.appel_termine = True
                st.rerun()
            
            st.markdown("<p style='text-align:center;'><a href='#top'>⬆️ Remonter en haut</a></p>", unsafe_allow_html=True)

# =======================
# 4. RÉCEPTION & MANAGER
# =======================
def show_reception():
    st.title("💁 Réception - Gestion des Absences")

    if df_all.empty:
        st.warning("Chargement des données...")
        return

    # Préparation des données
    df_work = df_all.copy()
    if "Date_dt" not in df_work.columns and "Date" in df_work.columns:
         df_work["Date_dt"] = pd.to_datetime(df_work["Date"], errors='coerce')
    
    if "Traite" not in df_work.columns: df_work["Traite"] = False

    # Onglets de travail
    tab_todo, tab_history = st.tabs(["⚡ À TRAITER (Actions)", "✅ Historique Traité"])

    # ========================================================
    # ONGLET 1 : LES ACTIONS A FAIRE
    # ========================================================
    with tab_todo:
        # Filtre : Absent ET Pas Traité
        df_todo = df_work[ (df_work["Statut"] == "Absent") & (df_work["Traite"] != True) ]
        
        if df_todo.empty:
            st.success("🎉 Tout est à jour ! Aucune absence à traiter.")
        else:
            st.write(f"Il reste **{len(df_todo)} absences** en attente de traitement.")
            
            clients_a_traiter = df_todo["Nom"].unique()
            client_select = st.selectbox("Sélectionner un client à traiter", clients_a_traiter)
            
            if client_select:
                # 1. Calcul du niveau (basé sur historique complet)
                all_abs = df_work[(df_work["Nom"] == client_select) & (df_work["Statut"] == "Absent")]
                nb_total = len(all_abs)
                
                # Récup seuils
                s1 = st.session_state.get("p1_val", 1)
                s2 = st.session_state.get("p2_val", 3)
                s3 = st.session_state.get("p3_val", 5)
                
                # Détermination du niveau
                niveau = 1
                if nb_total >= s3: niveau = 3
                elif nb_total >= s2: niveau = 2
                
                # Affichage de l'alerte
                if niveau == 3:
                    st.error(f"🔴 NIVEAU 3 - CONVOCATION ({nb_total} absences)")
                elif niveau == 2:
                    st.warning(f"🟠 NIVEAU 2 - APPEL TÉLÉPHONIQUE ({nb_total} absences)")
                else:
                    st.info(f"🟡 NIVEAU 1 - MAIL DE RAPPEL ({nb_total} absences)")

                # 2. Récupération des détails (dates) pour ce client (seulement celles non traitées)
                abs_a_traiter = df_todo[df_todo["Nom"] == client_select].sort_values("Date_dt", ascending=False)
                ids_a_traiter = []
                txt_details = []
                
                for _, row in abs_a_traiter.iterrows():
                    ids_a_traiter.append(row['id'])
                    d = row["Date_dt"].strftime("%d/%m") if pd.notnull(row["Date_dt"]) else "?"
                    c = row.get("Cours", "Séance")
                    txt_details.append(f"- {c} le {d}")
                
                details_str = "\n".join(txt_details)

                # 3. ACTION SELON LE NIVEAU
                msg_final = ""
                
                if niveau == 2:
                    # CAS P2 : APPEL (Pas de message à copier, juste un script)
                    st.markdown("### 📞 Action : Appeler le client")
                    st.write("Script : *'Bonjour, nous avons remarqué plusieurs absences (3+). Tout va bien ?'*")
                    label_bouton = "✅ J'ai appelé le client (Enregistrer la trace)"
                    
                elif niveau == 3:
                    # CAS P3 : CONVOCATION (Message spécial)
                    st.markdown("### ✉️ Action : Envoyer Convocation")
                    tpl = st.session_state.get("msg_p3_tpl", "Bonjour {prenom}, RDV nécessaire ({details}).")
                    msg_final = tpl.replace("{prenom}", client_select).replace("{details}", details_str)
                    st.text_area("Message à copier :", value=msg_final, height=200)
                    label_bouton = "✅ Message Convocation envoyé"
                    
                else:
                    # CAS P1 : MAIL SIMPLE
                    st.markdown("### 📧 Action : Envoyer Mail")
                    tpl = st.session_state.get("msg_tpl", "Bonjour {prenom}, absences : {details}.")
                    msg_final = tpl.replace("{prenom}", client_select).replace("{details}", details_str)
                    st.text_area("Message à copier :", value=msg_final, height=200)
                    label_bouton = "✅ Mail envoyé"

                # 4. BOUTON DE VALIDATION (Commun à tous)
                if st.button(label_bouton, type="primary"):
                    progress = st.progress(0)
                    date_now = datetime.now().strftime("%Y-%m-%d %H:%M") # Date et Heure actuelles
                    
                    for idx, id_airtable in enumerate(ids_a_traiter):
                        try:
                            # On met à jour : Traite = Vrai ET Date_Traitement = Maintenant
                            table.update(id_airtable, {
                                "Traite": True,
                                "Date_Traitement": date_now
                            })
                            progress.progress((idx + 1) / len(ids_a_traiter))
                        except Exception as e:
                            st.error(f"Erreur : {e}")
                    
                    st.success(f"Dossier {client_select} traité et archivé avec la date du {date_now} !")
                    import time
                    time.sleep(1.5)
                    st.rerun()

    # ========================================================
    # ONGLET 2 : HISTORIQUE (Avec la date !)
    # ========================================================
    with tab_history:
        st.markdown("### 🕵️ Suivi des actions effectuées")
        
        # On prend ceux qui sont traités
        df_done = df_work[ (df_work["Statut"] == "Absent") & (df_work["Traite"] == True) ].copy()
        
        if not df_done.empty:
            # On vérifie si la colonne date traitement existe pour l'affichage
            cols_show = ["Nom", "Date", "Cours"]
            if "Date_Traitement" in df_done.columns:
                cols_show.append("Date_Traitement")
                # Petit tri pour voir les derniers traités en haut
                df_done.sort_values("Date_Traitement", ascending=False, inplace=True)
            
            st.dataframe(
                df_done[cols_show], 
                use_container_width=True,
                column_config={
                    "Date_Traitement": st.column_config.DatetimeColumn("Traité le", format="D MMM YYYY, HH:mm"),
                    "Date": st.column_config.DateColumn("Date Absence", format="D MMM YYYY")
                }
            )
        else:
            st.info("Aucun historique disponible.")
# =======================
# 4. ESPACE MANAGER (VERSION PRO CONFIG P1/P2/P3)
# =======================
# =======================
# 4. ESPACE MANAGER (DASHBOARD ANALYTIQUE + CONFIG)
# =======================
def show_manager():
    # Style CSS pour les métriques
    st.markdown("""
        <style>
        .stMetric { background-color: #0E1117; border: 1px solid #303030; padding: 15px; border-radius: 5px; }
        </style>
    """, unsafe_allow_html=True)

    st.title("📊 Manager - Analyse & Pilotage")
    
    # Sécurité
    if st.sidebar.text_input("Code Manager", type="password") != MANAGER_PASSWORD:
        st.info("Veuillez vous identifier dans la barre latérale.")
        return

    if df_all.empty:
        st.warning("Aucune donnée disponible pour le moment.")
        return

    # --- PRÉPARATION DES DONNÉES POUR L'ANALYSE ---
    df_ana = df_all.copy()
    
    # Conversion dates
    if "Date_dt" not in df_ana.columns and "Date" in df_ana.columns:
         df_ana["Date_dt"] = pd.to_datetime(df_ana["Date"], errors='coerce')

    # Création colonne "Jour" (Lundi, Mardi...)
    jours_fr = {0: "Lundi", 1: "Mardi", 2: "Mercredi", 3: "Jeudi", 4: "Vendredi", 5: "Samedi", 6: "Dimanche"}
    df_ana["Jour_Num"] = df_ana["Date_dt"].dt.dayofweek
    df_ana["Jour"] = df_ana["Jour_Num"].map(jours_fr)

    # Remplissage des vides pour Cours/Heure
    if "Cours" not in df_ana.columns: df_ana["Cours"] = "Inconnu"
    if "Heure" not in df_ana.columns: df_ana["Heure"] = "?"
    df_ana["Cours"] = df_ana["Cours"].fillna("Inconnu")
    df_ana["Heure"] = df_ana["Heure"].fillna("?")

    # --- LES 2 ONGLETS DU MANAGER ---
    tab_dash, tab_config = st.tabs(["📊 DASHBOARD GLOBAL", "⚙️ CONFIGURATION"])

    # ========================================================
    # ONGLET 1 : LE DASHBOARD (Stats, Graphiques, Tops)
    # ========================================================
    with tab_dash:
        st.subheader("Vue d'ensemble")
        
        # 1. KPIs (Indicateurs Clés)
        nb_total_lignes = len(df_ana)
        nb_abs = len(df_ana[df_ana["Statut"] == "Absent"])
        nb_pres = len(df_ana[df_ana["Statut"] == "Présent"])
        taux_pres = (nb_pres / nb_total_lignes * 100) if nb_total_lignes > 0 else 0
        nb_clients_uniques = df_ana["Nom"].nunique()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Séances", nb_total_lignes)
        c2.metric("Clients Actifs", nb_clients_uniques)
        c3.metric("Total Absences", nb_abs, delta_color="inverse")
        c4.metric("Taux de Présence", f"{taux_pres:.1f}%")

        st.write("---")

        # 2. GRAPHIQUE D'ÉVOLUTION
        st.subheader("📈 Évolution de la fréquentation")
        # On groupe par date et statut
        chart_data = df_ana.groupby(["Date_dt", "Statut"]).size().unstack().fillna(0)
        st.bar_chart(chart_data, height=300)

        st.write("---")

        # 3. STATS PAR COURS & CRÉNEAUX
        col_g, col_d = st.columns(2)
        
        with col_g:
            st.subheader("🏊 Par Cours")
            # Compte le nombre total de séances par type de cours
            stats_cours = df_ana["Cours"].value_counts().reset_index()
            stats_cours.columns = ["Cours", "Nb Inscrits"]
            st.dataframe(stats_cours, use_container_width=True, hide_index=True)
            
        with col_d:
            st.subheader("⏰ Par Créneau Horaire")
            stats_heure = df_ana["Heure"].value_counts().reset_index()
            stats_heure.columns = ["Heure", "Nb Inscrits"]
            st.dataframe(stats_heure, use_container_width=True, hide_index=True)

        st.write("---")

        # 4. STATS PAR JOURS DE LA SEMAINE
        st.subheader("📅 Affluence par Jour")
        # On trie par ordre de la semaine (0=Lundi)
        stats_jour = df_ana.groupby(["Jour_Num", "Jour"]).size().reset_index(name="Total")
        stats_jour = stats_jour.sort_values("Jour_Num").set_index("Jour")["Total"]
        st.bar_chart(stats_jour)

        st.write("---")

        # 5. LES TOP 10 (Absents & Présents)
        c_top1, c_top2 = st.columns(2)

        with c_top1:
            st.subheader("🚨 TOP 10 - Les + Absents")
            df_abs_only = df_ana[df_ana["Statut"] == "Absent"]
            if not df_abs_only.empty:
                top_abs = df_abs_only["Nom"].value_counts().head(10).reset_index()
                top_abs.columns = ["Nom", "Nb Absences"]
                st.dataframe(top_abs, use_container_width=True, hide_index=True)
            else:
                st.success("Aucun absent ! Bravo.")

        with c_top2:
            st.subheader("🏆 TOP 10 - Les + Assidus")
            df_pres_only = df_ana[df_ana["Statut"] == "Présent"]
            if not df_pres_only.empty:
                top_pres = df_pres_only["Nom"].value_counts().head(10).reset_index()
                top_pres.columns = ["Nom", "Nb Présences"]
                st.dataframe(top_pres, use_container_width=True, hide_index=True)
            else:
                st.info("Pas encore de données de présence.")

    # ========================================================
    # ONGLET 2 : CONFIGURATION (Seuils & Messages)
    # ========================================================
    with tab_config:
        st.header("⚙️ Configuration des Relances")
        st.info("C'est ici que vous définissez les règles pour l'équipe Réception.")

        c_seuils, c_msg = st.columns([1, 1])
        
        with c_seuils:
            st.subheader("Paliers d'absences")
            
            st.markdown("**Niveau 1 (Mail)**")
            c1a, c1b = st.columns([1, 2])
            st.number_input("Seuil P1", key="p1_val", value=1)
            st.text_input("Label P1", key="p1_label", value="Mail Rappel")
            
            st.markdown("**Niveau 2 (Téléphone)**")
            c2a, c2b = st.columns([1, 2])
            st.number_input("Seuil P2", key="p2_val", value=3)
            st.text_input("Label P2", key="p2_label", value="Appel Tel.")
            
            st.markdown("**Niveau 3 (Convocation)**")
            c3a, c3b = st.columns([1, 2])
            st.number_input("Seuil P3", key="p3_val", value=5)
            st.text_input("Label P3", key="p3_label", value="Convocation")
            
        with c_msg:
            st.subheader("Messages Types")
            
            st.markdown("**Message P1 (Mail)**")
            default_p1 = "Bonjour {prenom},\n\nSauf erreur, vous avez manqué ces séances :\n{details}\n\nMerci de confirmer votre présence."
            st.text_area("Template", key="msg_tpl", value=default_p1, height=150)

            st.markdown("**Message P3 (Convocation)**")
            default_p3 = "Bonjour {prenom},\n\nCompte tenu de vos absences ({details}), merci de passer à l'accueil pour un point."
            st.text_area("Template P3", key="msg_p3_tpl", value=default_p3, height=150)

        if st.button("💾 Enregistrer la configuration"):
            # Note: Streamlit enregistre automatiquement dans session_state les clés key="..."
            st.success("Configuration sauvegardée pour la session !")

# =======================
# 5. HUB D'ACCUEIL
# =======================
def show_main_hub():
    st.markdown("<h1 style='text-align: center;'>🏊‍♂️ Piscine Pro</h1>", unsafe_allow_html=True)
    st.write("---")
    c1, c2, c3 = st.columns(3)
    if c1.button("👨‍🏫 MAÎTRE-NAGEUR", use_container_width=True):
        st.session_state.current_page = "MN"; st.rerun()
    if c2.button("💁 RÉCEPTION", use_container_width=True):
        st.session_state.current_page = "REC"; st.rerun()
    if c3.button("📊 MANAGER", use_container_width=True):
        st.session_state.current_page = "MGR"; st.rerun()

if 'current_page' not in st.session_state: st.session_state.current_page = "HUB"
if st.session_state.current_page != "HUB":
    if st.sidebar.button("🏠 Accueil"):
        st.session_state.current_page = "HUB"; st.rerun()

if st.session_state.current_page == "HUB": show_main_hub()
elif st.session_state.current_page == "MN": show_maitre_nageur()
elif st.session_state.current_page == "REC": show_reception()
elif st.session_state.current_page == "MGR": show_manager()

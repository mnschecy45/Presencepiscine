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
# 4. ESPACE MANAGER (FINAL : NETTOYAGE AUTO HEURE + DESIGN)
# =======================
def show_manager():
    # 1. CSS : STYLE CLAIR
    st.markdown("""
        <style>
        .stMetric {
            background-color: #f8f9fa;
            border: 1px solid #dee2e6;
            padding: 15px;
            border-radius: 10px;
            color: #31333F;
        }
        [data-testid="stMetricLabel"] { font-weight: bold; color: #666; }
        [data-testid="stMetricValue"] { color: #000; }
        </style>
    """, unsafe_allow_html=True)

    st.title("📊 Manager - Pilotage")

    # LOGIN
    if st.sidebar.text_input("Code Manager", type="password") != MANAGER_PASSWORD:
        st.info("Veuillez vous identifier à gauche (Menu >).")
        return

    if df_all.empty:
        st.warning("Aucune donnée.")
        return

    # --- PRÉPARATION DONNÉES ---
    df_ana = df_all.copy()
    if "Date_dt" not in df_ana.columns and "Date" in df_ana.columns:
         df_ana["Date_dt"] = pd.to_datetime(df_ana["Date"], errors='coerce')
    
    # Nettoyage de base
    df_ana = df_ana.dropna(subset=["Date_dt"])
    if "Cours" not in df_ana.columns: df_ana["Cours"] = "Inconnu"
    if "Heure" not in df_ana.columns: df_ana["Heure"] = "?"
    
    # --- LE CORRECTIF MAGIQUE POUR L'HEURE ---
    def nettoyer_heure(val):
        s = str(val)
        # Si ça ressemble à une date longue (ex: 2025-12-21 18:40:00)
        if len(s) > 8 and (" " in s or "T" in s):
            # On essaie de prendre juste la partie Heure:Minute
            try:
                # On remplace le T par espace, on coupe à l'espace, on prend la fin
                partie_heure = s.replace("T", " ").split(" ")[-1]
                return partie_heure[:5] # Garde les 5 premiers caractères (HH:MM)
            except:
                return s
        return s

    df_ana["Heure"] = df_ana["Heure"].apply(nettoyer_heure)
    df_ana["Cours"] = df_ana["Cours"].fillna("Inconnu")

    # Colonnes temporelles
    df_ana["Annee"] = df_ana["Date_dt"].dt.year
    df_ana["Mois"] = df_ana["Date_dt"].dt.month
    jours_fr = {0: "Lundi", 1: "Mardi", 2: "Mercredi", 3: "Jeudi", 4: "Vendredi", 5: "Samedi", 6: "Dimanche"}
    df_ana["Jour_Num"] = df_ana["Date_dt"].dt.dayofweek
    df_ana["Jour"] = df_ana["Jour_Num"].map(jours_fr)

    # ==========================================
    # 🕵️ FILTRES (BARRE LATÉRALE)
    # ==========================================
    st.sidebar.header("📅 Filtres")
    
    annees_dispo = sorted(df_ana["Annee"].unique(), reverse=True)
    annee_select = st.sidebar.selectbox("Année", annees_dispo)
    
    df_annee = df_ana[df_ana["Annee"] == annee_select]
    moisc_dispo = sorted(df_annee["Mois"].unique())
    liste_mois = ["TOUS"] + [pd.to_datetime(f"2022-{m}-01").strftime("%B") for m in moisc_dispo]
    
    mois_select_txt = st.sidebar.selectbox("Mois", liste_mois)

    # Application filtre
    if mois_select_txt == "TOUS":
        df_filtered = df_annee
        titre_periode = f"Année {annee_select}"
    else:
        mois_index = liste_mois.index(mois_select_txt)
        mois_num = moisc_dispo[mois_index - 1]
        df_filtered = df_annee[df_annee["Mois"] == mois_num]
        titre_periode = f"{mois_select_txt} {annee_select}"

    st.subheader(f"Analyse : {titre_periode}")

    # ==========================================
    # DASHBOARD
    # ==========================================
    
    tab_dash, tab_config = st.tabs(["📊 DASHBOARD", "⚙️ CONFIG"])

    with tab_dash:
        # 1. KPIs
        nb_inscrits = len(df_filtered)
        nb_presents = len(df_filtered[df_filtered["Statut"] == "Présent"])
        nb_absents = len(df_filtered[df_filtered["Statut"] == "Absent"])
        taux_remplissage = (nb_presents / nb_inscrits * 100) if nb_inscrits > 0 else 0
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Inscrits", nb_inscrits)
        c2.metric("Présents", nb_presents, delta=f"{taux_remplissage:.1f}%")
        c3.metric("Absents", nb_absents, delta_color="inverse")
        # Exemple CA (vous pourrez ajuster le prix)
        c4.metric("CA Estimé", f"{nb_presents * 15} €")

        st.write("---")

        # 2. TABLEAU DÉTAILLÉ (Théorique vs Réel)
        st.subheader("Détails par Créneau")
        
        if not df_filtered.empty:
            synthese = df_filtered.groupby(["Jour_Num", "Jour", "Heure", "Cours"]).agg(
                Inscrits=('Nom', 'count'),
                Presents=('Statut', lambda x: (x == 'Présent').sum())
            ).reset_index()
            
            synthese["Absents"] = synthese["Inscrits"] - synthese["Presents"]
            synthese["Taux %"] = (synthese["Presents"] / synthese["Inscrits"] * 100).round(1)
            synthese = synthese.sort_values(by=["Jour_Num", "Heure"])
            
            st.dataframe(
                synthese[["Jour", "Heure", "Cours", "Inscrits", "Presents", "Absents", "Taux %"]],
                use_container_width=True,
                column_config={
                    "Taux %": st.column_config.ProgressColumn("Remplissage", format="%.0f%%", min_value=0, max_value=100)
                },
                hide_index=True
            )
        else:
            st.info("Pas de données sur cette période.")

        # 3. GRAPHIQUES
        st.write("---")
        c_g1, c_g2 = st.columns(2)
        
        with c_g1:
            st.subheader("Top Cours (Inscrits)")
            if not df_filtered.empty:
                st.bar_chart(df_filtered["Cours"].value_counts())
        
        with c_g2:
            st.subheader("Affluence Semaine")
            if not df_filtered.empty:
                # On trie correctement Lundi -> Dimanche
                semaine = df_filtered.groupby("Jour").size()
                ordre = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
                semaine = semaine.reindex(ordre, fill_value=0)
                st.bar_chart(semaine, color="#76b900")

    # ==========================================
    # CONFIGURATION
    # ==========================================
    with tab_config:
        st.header("⚙️ Paramètres")
        c_seuils, c_msg = st.columns([1, 1])
        with c_seuils:
            st.subheader("Seuils P1/P2/P3")
            st.number_input("Seuil P1", key="p1_val", value=1)
            st.number_input("Seuil P2", key="p2_val", value=3)
            st.number_input("Seuil P3", key="p3_val", value=5)

        with c_msg:
            st.subheader("Messages")
            st.text_area("Message P1", key="msg_tpl", value="Bonjour...", height=100)
            st.text_area("Message P3", key="msg_p3_tpl", value="Convocation...", height=100)
            
        if st.button("💾 Sauvegarder"):
            st.success("Sauvegardé !")
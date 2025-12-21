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
try:
    api = Api(API_TOKEN)
    table = api.table(BASE_ID, TABLE_NAME)
    
    # On récupère toutes les données pour l'historique (Réception/Manager)
    records = table.all()
    if records:
        # On transforme le format bizarre d'Airtable en tableau simple
        data = [r['fields'] for r in records]
        df_all = pd.DataFrame(data)
        
        # Petit nettoyage des dates pour que les calculs marchent
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
            # On convertit le booléen 'Absent' en texte "Absent" ou "Présent"
            statut_final = "Absent" if row["Absent"] else "Présent"
            
            # Conversion de la date en chaine de caractères pour Airtable
            date_str = row["Date"].strftime("%Y-%m-%d") if isinstance(row["Date"], (date, datetime)) else str(row["Date"])

            record = {
                "Nom": row["Nom"],
                "Statut": statut_final, 
                "Date": date_str,
                # On peut ajouter d'autres champs si ils existent dans Airtable
                # "Cours": row["Cours"], 
                # "Heure": row["Heure"]
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
    st.title("💁 Réception")
    s = st.text_input("🔎 Rechercher par Nom")
    if s and not df_all.empty:
        # On vérifie que les colonnes existent dans Airtable
        cols_to_search = []
        if "Nom" in df_all.columns: cols_to_search.append("Nom")
        if "Prenom" in df_all.columns: cols_to_search.append("Prenom")
        
        if cols_to_search:
            mask = pd.DataFrame(False, index=df_all.index, columns=['match'])
            for col in cols_to_search:
                mask['match'] |= df_all[col].astype(str).str.contains(s, case=False, na=False)
            
            res = df_all[mask['match']]
            
            cols_show = ["Date", "Statut"] # On adapte aux colonnes Airtable
            if "Cours" in df_all.columns: cols_show.append("Cours")
            
            st.dataframe(res[cols_show].sort_values("Date", ascending=False), use_container_width=True)
    elif df_all.empty:
        st.info("La base de données est vide ou inaccessible.")

# =======================
# 4. ESPACE MANAGER (VERSION PRO CONFIG P1/P2/P3)
# =======================
def show_manager():
    # CSS pour le style "Pro"
    st.markdown("""
        <style>
        .stMetric { background-color: #0E1117; border: 1px solid #303030; padding: 15px; border-radius: 5px; }
        .stAlert { background-color: #1E1E1E; color: white; border: 1px solid #444; }
        </style>
    """, unsafe_allow_html=True)

    st.title("📊 Manager")
    
    # LOGIN
    password = st.sidebar.text_input("🔒 Code Manager", type="password")
    if password != MANAGER_PASSWORD:
        st.info("Mot de passe requis dans la barre latérale.")
        return

    # DONNÉES
    if df_all.empty:
        st.warning("Base de données vide.")
        return

    # Préparation des dates
    df_work = df_all.copy()
    if "Date_dt" not in df_work.columns and "Date" in df_work.columns:
         df_work["Date_dt"] = pd.to_datetime(df_work["Date"], errors='coerce')
    
    # --- ONGLETS ---
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 Dashboard", "🗓️ Planning Semaine", "📉 Risque Départ", "⚡ Actions", "⚙️ Config"])

    # ==========================
    # TAB 1 : DASHBOARD
    # ==========================
    with tab1:
        st.subheader("Vue d'ensemble")
        today = pd.Timestamp.now().normalize()
        
        nb_total = len(df_work)
        nb_absents = len(df_work[df_work["Statut"] == "Absent"])
        taux = ((nb_total - nb_absents) / nb_total * 100) if nb_total > 0 else 0
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Inscrits", nb_total)
        c2.metric("Absents", nb_absents)
        c3.metric("Présence", f"{taux:.1f}%")
        c4.metric("Dernier ajout", df_work["Date"].max() if not df_work.empty else "-")

        st.write("---")
        daily = df_work[df_work["Statut"] == "Présent"].groupby("Date_dt").size()
        st.area_chart(daily, height=250)

        c_g, c_d = st.columns(2)
        with c_g:
            st.markdown("### Par Cours")
            if "Cours" in df_work.columns:
                st.dataframe(df_work["Cours"].value_counts(), use_container_width=True)
        with c_d:
            st.markdown("### Par Créneau")
            if "Heure" in df_work.columns:
                st.dataframe(df_work["Heure"].value_counts(), use_container_width=True)

    # ==========================
    # TAB 5 : CONFIG (Réglages Seuils & Message)
    # ==========================
    with tab5:
        st.header("⚙️ Config")
        c_seuils, c_msg = st.columns([1, 1])
        
        with c_seuils:
            st.subheader("Seuils d'alerte")
            # P1
            c1a, c1b = st.columns([1, 2])
            p1_val = c1a.number_input("Seuil P1 (Jours)", value=st.session_state.get("p1_val", 7), min_value=1)
            p1_label = c1b.text_input("Label P1", value=st.session_state.get("p1_label", "Envoyer un mail"))
            # P2
            c2a, c2b = st.columns([1, 2])
            p2_val = c2a.number_input("Seuil P2 (Jours)", value=st.session_state.get("p2_val", 14), min_value=1)
            p2_label = c2b.text_input("Label P2", value=st.session_state.get("p2_label", "Appeler le client"))
            # P3
            c3a, c3b = st.columns([1, 2])
            p3_val = c3a.number_input("Seuil P3 (Jours)", value=st.session_state.get("p3_val", 21), min_value=1)
            p3_label = c3b.text_input("Label P3", value=st.session_state.get("p3_label", "Convocation / RDV"))
            
            if st.button("💾 Sauvegarder Seuils"):
                st.session_state["p1_val"] = p1_val; st.session_state["p1_label"] = p1_label
                st.session_state["p2_val"] = p2_val; st.session_state["p2_label"] = p2_label
                st.session_state["p3_val"] = p3_val; st.session_state["p3_label"] = p3_label
                st.success("Seuils enregistrés !")

        with c_msg:
            st.subheader("Template du Message")
            st.caption("Utilisez {prenom} pour le nom et {details} pour la liste des absences.")
            default_msg = "Bonjour {prenom},\n\nSauf erreur de notre part, nous avons relevé les absences suivantes :\n{details}\n\nAfin de ne pas perdre le bénéfice de votre progression, merci de nous confirmer votre présence pour la prochaine séance.\n\nCordialement,\nL'équipe Piscine."
            tpl = st.text_area("Contenu", value=st.session_state.get("msg_tpl", default_msg), height=300)
            
            if st.button("💾 Sauvegarder Message"):
                st.session_state["msg_tpl"] = tpl
                st.success("Template enregistré !")

    # ==========================
    # TAB 3 : RISQUE DÉPART (Calcul automatique)
    # ==========================
    with tab3:
        st.subheader("📉 Risque Départ")
        today = pd.Timestamp.now().normalize()
        
        # On ne regarde que ceux qui sont déjà venus au moins une fois
        df_p = df_work[df_work["Statut"] == "Présent"]
        
        if not df_p.empty:
            last_venue = df_p.groupby("Nom")["Date_dt"].max().reset_index()
            last_venue["Jours_Absent"] = (today - last_venue["Date_dt"]).dt.days
            
            s1 = st.session_state.get("p1_val", 7)
            s2 = st.session_state.get("p2_val", 14)
            s3 = st.session_state.get("p3_val", 21)
            
            def get_niveau(jours):
                if jours >= s3: return f"🔴 P3 ({st.session_state.get('p3_label', 'Convocation')})"
                elif jours >= s2: return f"🟠 P2 ({st.session_state.get('p2_label', 'Appel')})"
                elif jours >= s1: return f"🟡 P1 ({st.session_state.get('p1_label', 'Mail')})"
                else: return "OK"

            last_venue["Niveau"] = last_venue["Jours_Absent"].apply(get_niveau)
            alertes = last_venue[last_venue["Niveau"] != "OK"].sort_values("Jours_Absent", ascending=False)
            
            st.dataframe(alertes, use_container_width=True)
        else:
            st.info("Pas assez de données de présence.")

    # ==========================
    # TAB 4 : ACTIONS (C'est ici que la magie opère !)
    # ==========================
    with tab4:
        st.subheader("⚡ Actions Re-quises")
        
        if 'alertes' in locals() and not alertes.empty:
            # Liste déroulante des gens à relancer
            liste_clients = alertes["Nom"].unique()
            client_select = st.selectbox("Sélectionner un client à traiter", liste_clients)
            
            if client_select:
                # 1. On récupère les infos générales
                info_client = alertes[alertes["Nom"] == client_select].iloc[0]
                niveau = info_client['Niveau']
                jours = info_client['Jours_Absent']
                
                st.markdown(f"**Statut :** {niveau} | **Absent depuis :** {jours} jours")
                
                # 2. ON GÉNÈRE LA LISTE DÉTAILLÉE DES ABSENCES (Le point clé !)
                # On filtre tout l'historique de CE client
                historique_client = df_work[df_work["Nom"] == client_select]
                # On ne garde que ses absences
                absences_client = historique_client[historique_client["Statut"] == "Absent"].sort_values("Date_dt", ascending=False)
                
                details_txt = ""
                if not absences_client.empty:
                    lignes = []
                    for idx, row in absences_client.iterrows():
                        # On formate la date (ex: 17/12)
                        date_str = row["Date_dt"].strftime("%d/%m") if pd.notnull(row["Date_dt"]) else "Date inconnue"
                        # On récupère l'heure et le cours (s'ils existent, sinon "?")
                        heure_str = row["Heure"] if "Heure" in row else "?"
                        cours_str = row["Cours"] if "Cours" in row else "?"
                        
                        # On construit la ligne : "- Le 17/12 à 12h15 (Aquabiking)"
                        lignes.append(f"- Le {date_str} à {heure_str} ({cours_str})")
                    
                    # On joint tout avec des sauts de ligne
                    details_txt = "\n".join(lignes)
                else:
                    details_txt = "(Aucune absence spécifique notée, client juste inactif)"

                # 3. Injection dans le template
                tpl = st.session_state.get("msg_tpl", "")
                # On remplace {details} par la liste qu'on vient de créer
                msg_final = tpl.replace("{prenom}", client_select).replace("{details}", details_txt)
                
                # 4. Affichage
                st.text_area("Message généré (prêt à copier) :", value=msg_final, height=300)
                
                # Bouton mailto (Bonus)
                if st.button("✅ Marquer comme FAIT (Simulation)"):
                    st.toast(f"Action enregistrée pour {client_select} !", icon="🎉")

        else:
            st.success("Aucune action requise pour le moment. Tout le monde est assidu ! 👏")

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

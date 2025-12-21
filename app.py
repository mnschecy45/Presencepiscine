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

def show_manager():
    # CSS pour cacher la barre de menu standard et faire "Pro"
    st.markdown("""
        <style>
        .stMetric {
            background-color: #0E1117;
            border: 1px solid #303030;
            padding: 15px;
            border-radius: 5px;
        }
        </style>
    """, unsafe_allow_html=True)

    st.title("📊 Espace Manager")
    
    # --- 1. LOGIN ---
    password = st.sidebar.text_input("🔒 Code Manager", type="password")
    if password != MANAGER_PASSWORD:
        st.info("Veuillez entrer le mot de passe dans la barre latérale à gauche.")
        return

    # --- 2. PRÉPARATION DES DONNÉES ---
    if df_all.empty:
        st.warning("⚠️ La base de données est vide. Faites des appels pour voir les statistiques.")
        return

    # On s'assure que les dates sont bien formatées
    df_work = df_all.copy()
    if "Date_dt" not in df_work.columns and "Date" in df_work.columns:
         df_work["Date_dt"] = pd.to_datetime(df_work["Date"], errors='coerce')
    
    # Nettoyage des données pour éviter les bugs
    df_work = df_work.dropna(subset=["Date_dt"])
    
    # --- 3. FILTRES LATÉRAUX (Comme sur votre image) ---
    st.sidebar.header("📅 Période & Filtres")
    
    filtre_periode = st.sidebar.radio(
        "Période", 
        ["Tout l'historique", "Ce mois-ci", "Cette semaine", "Aujourd'hui"],
        index=0
    )
    
    # Logique de filtre Date
    today = pd.Timestamp.now().normalize()
    if filtre_periode == "Ce mois-ci":
        start_date = today.replace(day=1)
        df_work = df_work[df_work["Date_dt"] >= start_date]
    elif filtre_periode == "Cette semaine":
        start_date = today - pd.Timedelta(days=today.weekday())
        df_work = df_work[df_work["Date_dt"] >= start_date]
    elif filtre_periode == "Aujourd'hui":
        df_work = df_work[df_work["Date_dt"] == today]

    # Filtre Cours (si la colonne existe)
    if "Cours" in df_work.columns:
        liste_cours = df_work["Cours"].unique().tolist()
        choix_cours = st.sidebar.multiselect("Filtrer par Cours", liste_cours, default=liste_cours)
        if choix_cours:
            df_work = df_work[df_work["Cours"].isin(choix_cours)]

    # --- 4. LES ONGLETS (DASHBOARD / RISQUE / CONFIG) ---
    tab1, tab2, tab3, tab4 = st.tabs(["📈 Dashboard", "📉 Risque Départ", "⚡ Actions", "⚙️ Config"])

    # ==========================
    # TAB 1 : DASHBOARD (VUE D'ENSEMBLE)
    # ==========================
    with tab1:
        st.subheader("Vue d'ensemble")
        
        # Calcul des KPIs
        nb_total = len(df_work)
        if nb_total > 0:
            nb_presents = len(df_work[df_work["Statut"] == "Présent"])
            nb_absents = len(df_work[df_work["Statut"] == "Absent"])
            taux_presence = (nb_presents / nb_total) * 100
        else:
            nb_presents = 0
            nb_absents = 0
            taux_presence = 0

        # Affichage des métriques sur une ligne
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Inscrits (Période)", nb_total)
        c2.metric("Absents", nb_absents, delta_color="inverse")
        c3.metric("Présence", f"{taux_presence:.1f}%")
        # Ici on pourrait mettre les "Nouveaux" si on avait la date d'inscription
        c4.metric("Clients Uniques", df_work["Nom"].nunique())

        st.write("---")

        # GRAPHIQUE 1 : Évolution de la présence
        st.subheader("Évolution de la fréquentation")
        if not df_work.empty:
            # On groupe par jour et on compte les présents
            daily_counts = df_work[df_work["Statut"] == "Présent"].groupby("Date_dt").size()
            st.bar_chart(daily_counts)
        else:
            st.info("Pas de données pour cette période.")

        # TABLEAUX DÉTAILLÉS (Si les colonnes existent)
        col_g, col_d = st.columns(2)
        
        with col_g:
            st.subheader("Par Cours")
            if "Cours" in df_work.columns:
                stats_cours = df_work.groupby("Cours")["Statut"].apply(lambda x: (x == "Présent").mean() * 100).reset_index(name="Taux Présence %")
                st.dataframe(stats_cours, use_container_width=True)
            else:
                st.caption("Ajoutez une colonne 'Cours' dans Airtable pour voir ce tableau.")

        with col_d:
            st.subheader("Top Absents (Période)")
            top_abs = df_work[df_work["Statut"] == "Absent"]["Nom"].value_counts().head(5).reset_index()
            top_abs.columns = ["Nom", "Nb Absences"]
            st.dataframe(top_abs, use_container_width=True)

    # ==========================
    # TAB 2 : RISQUE DÉPART (ALERTES)
    # ==========================
    with tab2:
        st.subheader("🕵️ Détection des Clients à Risque")
        
        # Récupération du seuil depuis la config (ou valeur par défaut)
        seuil_jours = st.session_state.get("config_seuil", 21)
        st.info(f"Affichage des clients n'ayant pas assisté à un cours depuis plus de **{seuil_jours} jours**.")

        # Calcul des dernières venues (sur TOUTE la base, pas juste la période filtrée)
        # On prend df_all pour avoir l'historique complet
        df_risk = df_all.copy()
        if "Date_dt" not in df_risk.columns:
             df_risk["Date_dt"] = pd.to_datetime(df_risk["Date"], errors='coerce')
        
        df_p = df_risk[df_risk["Statut"] == "Présent"]
        
        if not df_p.empty:
            last_venue = df_p.groupby("Nom")["Date_dt"].max().reset_index()
            last_venue["Jours_Absent"] = (today - last_venue["Date_dt"]).dt.days
            
            # Filtre
            alertes = last_venue[last_venue["Jours_Absent"] >= seuil_jours].sort_values("Jours_Absent", ascending=False)
            
            if not alertes.empty:
                st.dataframe(
                    alertes.rename(columns={"Date_dt": "Dernière Venue", "Jours_Absent": "Jours d'Absence"}),
                    use_container_width=True
                )
            else:
                st.success("✅ Aucun client à risque (tous sont venus récemment).")
        else:
            st.warning("Pas assez de données de présence pour calculer les risques.")

    # ==========================
    # TAB 3 : ACTIONS (MESSAGES)
    # ==========================
    with tab3:
        st.subheader("📧 Générateur de Messages")
        
        # Récupération des templates
        objet_defaut = st.session_state.get("config_objet", "Des nouvelles de votre piscine")
        msg_defaut = st.session_state.get("config_msg", "Bonjour {nom},\n\nCela fait un moment qu'on ne vous a pas vu. Tout va bien ?")

        # Sélection du client (parmi ceux à risque identifiés dans l'onglet 2)
        # On recalcule vite fait la liste des alertes pour le menu déroulant
        if 'alertes' in locals() and not alertes.empty:
            client_select = st.selectbox("Choisir un client à relancer :", alertes["Nom"].tolist())
            
            if client_select:
                # Infos du client
                info_c = alertes[alertes["Nom"] == client_select].iloc[0]
                jours_abs = info_c["Jours_Absent"]
                
                st.markdown(f"**Client :** {client_select} (Absent depuis {jours_abs} jours)")
                
                # Génération du message
                msg_final = msg_defaut.replace("{nom}", client_select)
                
                st.text_area("Copier le message :", value=msg_final, height=150)
                
                # Lien Mailto
                link = f"mailto:?subject={objet_defaut}&body={msg_final.replace(chr(10), '%0D%0A')}"
                st.markdown(f"<a href='{link}' target='_blank' style='background-color:#FF4B4B; color:white; padding:10px; border-radius:5px; text-decoration:none;'>🚀 Ouvrir mon logiciel mail</a>", unsafe_allow_html=True)
        else:
            st.info("Aucun client à relancer pour le moment (vérifiez l'onglet 'Risque Départ').")

    # ==========================
    # TAB 4 : CONFIGURATION
    # ==========================
    with tab4:
        st.subheader("⚙️ Paramètres du Manager")
        
        with st.form("config_form"):
            st.markdown("### Seuils")
            new_seuil = st.slider("Seuil d'alerte absence (jours)", 7, 90, 21)
            
            st.markdown("### Messages Types")
            new_objet = st.text_input("Objet du mail par défaut", value="Des nouvelles de votre piscine")
            new_msg = st.text_area(
                "Corps du message (utilisez {nom} pour le nom du client)", 
                value="Bonjour {nom},\n\nÇa fait longtemps ! On espère vous revoir vite au bord du bassin.\n\nCordialement,"
            )
            
            if st.form_submit_button("Enregistrer la configuration"):
                st.session_state["config_seuil"] = new_seuil
                st.session_state["config_objet"] = new_objet
                st.session_state["config_msg"] = new_msg
                st.success("Paramètres sauvegardés pour cette session !")
                st.rerun()

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

import streamlit as st
import pandas as pd
import pdfplumber
import re
import io
import json
from datetime import datetime, date, timedelta
from streamlit_gsheets import GSheetsConnection

# =======================
# 1. CONFIGURATION & SÉCURITÉ
# =======================
st.set_page_config(page_title="Piscine Pro - Gestion Cloud", layout="wide", page_icon="🏊‍♂️")

# Récupération des mots de passe depuis les Secrets ou valeurs par défaut
MANAGER_PASSWORD = st.secrets.get("MANAGER_PASSWORD", "manager")
ACCUEIL_PASSWORD = st.secrets.get("ACCUEIL_PASSWORD", "accueil")

# Connexion à Google Sheets (La base de données éternelle)
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
    df_all = conn.read(ttl=0) 
    if not df_all.empty:
        df_all["Date_dt"] = pd.to_datetime(df_all["Date"], dayfirst=True, errors='coerce')
except Exception as e:
    st.error("⚠️ Erreur de connexion au Cloud. Configurez les 'Secrets' sur Streamlit Cloud.")
    df_all = pd.DataFrame()

# =======================
# 2. MOTEUR DE SAUVEGARDE
# =======================
def save_data_to_cloud(df_new):
    existing_data = conn.read(ttl=0)
    df_new["Date"] = pd.to_datetime(df_new["Date"]).dt.strftime('%d/%m/%Y')
    updated_data = pd.concat([existing_data, df_new], ignore_index=True)
    conn.update(data=updated_data)

# =======================
# 3. ANALYSE PDF ROBUSTE
# =======================
def parse_pdf_complete(file_bytes):
    sessions, rows = [], []
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for idx, page in enumerate(pdf.pages):
                txt = page.extract_text()
                if not txt: continue
                lines = txt.splitlines()
                d_str = ""
                for l in lines[:5]:
                    m = re.search(r"\d{2}/\d{2}/\d{4}", l)
                    if m: d_str = m.group(0); break
                s_date = datetime.strptime(d_str, "%d/%m/%Y").date() if d_str else date.today()
                c_name, h_deb = "Cours Inconnu", ""
                for l in lines[:5]:
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
                    parts = l.split()
                    if len(parts) >= 3:
                        rows.append({
                            "Date": s_date, "Cours": c_name, "Heure": h_deb,
                            "Nom": parts[-1], "Prenom": " ".join(parts[1:-1]),
                            "Absent": False, "Manuel": False, "Session_ID": f"{s_date}_{h_deb}_{idx}"
                        })
    except Exception as e:
        st.error(f"Erreur lors de la lecture du PDF : {e}")
    return pd.DataFrame(rows)

# =======================
# 4. ESPACE MAÎTRE-NAGEUR (VERSION CORRIGÉE COULEURS)
# =======================
def show_maitre_nageur():
    st.title("👨‍🏫 Espace Appel Bassin")
    if st.session_state.get("appel_termine", False):
        st.success("✅ Appel enregistré et envoyé au Manager !")
        if st.button("Faire un nouvel appel"):
            st.session_state.appel_termine = False
            st.rerun()
        return

    up = st.file_uploader("Charger la feuille d'appel PDF", type=["pdf"])
    if up:
        df_appel = parse_pdf_complete(up.read())
        if df_appel.empty:
            st.warning("Aucun élève trouvé dans ce PDF.")
            return

        st.info(f"📅 Cours : {df_appel['Cours'].iloc[0]} à {df_appel['Heure'].iloc[0]}")
        for idx, row in df_appel.iterrows():
            key = f"pres_{idx}"
            if key not in st.session_state: st.session_state[key] = False
            
            # --- CORRECTION COULEURS ICI ---
            bg_color = "#dcfce7" if st.session_state[key] else "#fee2e2"
            # On force la couleur du texte en noir (color: black;) pour la lisibilité
            col_nom, col_check = st.columns([4, 1])
            col_nom.markdown(f"<div style='padding:12px; background:{bg_color}; color: black; border-radius:8px; margin-bottom:5px;'><strong>{row['Nom'].upper()} {row['Prenom']}</strong></div>", unsafe_allow_html=True)
            
            st.session_state[key] = col_check.checkbox("Présent", key=f"cb_{idx}", value=st.session_state[key], label_visibility="collapsed")
            df_appel.at[idx, "Absent"] = not st.session_state[key]

        st.markdown("---")
        nb_presents = len(df_appel[df_appel["Absent"] == False])
        st.subheader("📋 Résumé de l'appel")
        res1, res2, res3 = st.columns(3)
        res1.metric("Inscrits PDF", len(df_appel))
        res2.metric("Absents", len(df_appel) - nb_presents, delta_color="inverse")
        res3.metric("TOTAL DANS L'EAU", nb_presents)

        if st.button("💾 ENREGISTRER L'APPEL", type="primary", use_container_width=True):
            save_data_to_cloud(df_appel)
            st.session_state.appel_termine = True
            st.rerun()


# =======================
# 5. ESPACE MANAGER
# =======================
def show_manager():
    st.title("📊 Pilotage & Statistiques")
    if not st.session_state.get("mgr_auth", False):
        if st.text_input("Code confidentiel Manager", type="password") == MANAGER_PASSWORD:
            st.session_state.mgr_auth = True
            st.rerun()
        st.stop()

    if df_all.empty:
        st.info("La base de données est vide.")
        return

    t_db, t_plan, t_risk = st.tabs(["📈 Dashboard", "📅 Planning", "📉 Risque Départ"])
    with t_db:
        pdf_data = df_all[df_all["Manuel"] == False]
        st.subheader("Vue d'ensemble")
        k1, k2, k3 = st.columns(3)
        k1.metric("Inscrits PDF", len(pdf_data))
        k2.metric("Absents PDF", int(pdf_data["Absent"].sum()), delta_color="inverse")
        k3.metric("Total réels (dans l'eau)", len(df_all[df_all["Absent"] == False]))
        st.markdown("---")
        st.subheader("🕒 Fréquentation par créneau")
        stats_cr = pdf_data.groupby(["Cours", "Heure"]).agg(Inscrits=("Nom", "count"), Absents=("Absent", "sum")).reset_index()
        st.dataframe(stats_cr, use_container_width=True)

    with t_risk:
        st.subheader("Analyse du Churn (> 21 jours)")
        today = pd.Timestamp.now().normalize()
        df_p = df_all[df_all["Absent"] == False]
        if not df_p.empty:
            last_seen = df_p.groupby(["Nom", "Prenom"])["Date_dt"].max().reset_index()
            last_seen["Jours_depuis_visite"] = (today - last_seen["Date_dt"]).dt.days
            st.dataframe(last_seen[last_seen["Jours_depuis_visite"] > 21])

# =======================
# 6. ESPACE RÉCEPTION
# =======================
def show_reception():
    st.title("💁 Recherche & Relances")
    search = st.text_input("🔎 Rechercher un adhérent")
    if search and not df_all.empty:
        mask = df_all["Nom"].str.contains(search, case=False, na=False) | df_all["Prenom"].str.contains(search, case=False, na=False)
        resultats = df_all[mask]
        if not resultats.empty:
            for _, p in resultats[["Nom", "Prenom"]].drop_duplicates().iterrows():
                with st.expander(f"👤 {p['Nom']} {p['Prenom']}"):
                    st.table(resultats[(resultats["Nom"] == p["Nom"]) & (resultats["Prenom"] == p["Prenom"])][["Date", "Cours", "Absent"]])

# =======================
# 7. PAGE D'ACCUEIL
# =======================
def show_main_hub():
    st.markdown("<h1 style='text-align: center; color: #1E3A8A;'>🏊‍♂️ Application Piscine Pro</h1>", unsafe_allow_html=True)
    st.write("##")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("👨‍🏫 MAÎTRE-NAGEUR", use_container_width=True):
            st.session_state.current_page = "MN"
            st.rerun()
    with c2:
        if st.button("💁 RÉCEPTION", use_container_width=True):
            st.session_state.current_page = "REC"
            st.rerun()
    with c3:
        if st.button("📊 MANAGER", use_container_width=True):
            st.session_state.current_page = "MGR"
            st.rerun()

# =======================
# 8. ROUTAGE
# =======================
if 'current_page' not in st.session_state: st.session_state.current_page = "HUB"
if st.session_state.current_page != "HUB":
    if st.sidebar.button("🏠 Retour à l'accueil"):
        st.session_state.current_page = "HUB"
        st.rerun()

if st.session_state.current_page == "HUB": show_main_hub()
elif st.session_state.current_page == "MN": show_maitre_nageur()
elif st.session_state.current_page == "REC": show_reception()
elif st.session_state.current_page == "MGR": show_manager()

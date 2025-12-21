import streamlit as st
import pandas as pd
import pdfplumber
import re
import io
from datetime import datetime, date
from streamlit_gsheets import GSheetsConnection

# =======================
# 1. CONFIGURATION GÉNÉRALE
# =======================
st.set_page_config(page_title="Piscine Pro - Gestion Cloud", layout="wide", page_icon="🏊‍♂️")

MANAGER_PASSWORD = st.secrets.get("MANAGER_PASSWORD", "manager")

try:
    conn = st.connection("gsheets", type=GSheetsConnection)
    df_all = conn.read(ttl=0)
    if not df_all.empty:
        df_all["Date_dt"] = pd.to_datetime(df_all["Date"], dayfirst=True, errors='coerce')
except:
    df_all = pd.DataFrame()

# =======================
# 2. LOGIQUE DE SAUVEGARDE & PDF
# =======================
def save_data_to_cloud(df_new):
    existing_data = conn.read(ttl=0)
    df_new["Date"] = pd.to_datetime(df_new["Date"]).dt.strftime('%d/%m/%Y')
    updated_data = pd.concat([existing_data, df_new], ignore_index=True)
    conn.update(data=updated_data)

def parse_pdf_complete(file_bytes):
    rows = []
    ignore_list = ["TCPDF", "www.", "places", "réservées", "disponibles", "ouvertes", "le ", " à ", "Page ", "Généré"]
    
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for idx, page in enumerate(pdf.pages):
                txt = page.extract_text()
                if not txt: continue
                lines = txt.splitlines()
                
                # Extraction Date
                d_str = ""
                for l in lines[:15]:
                    m = re.search(r"\d{2}/\d{2}/\d{4}", l)
                    if m: d_str = m.group(0); break
                s_date = datetime.strptime(d_str, "%d/%m/%Y").date() if d_str else date.today()
                
                # Extraction Cours et Heure
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
                    
                    # Nettoyage des chiffres (V4.3 logic)
                    l_clean = re.sub(r'\d+', '', l).strip()
                    l_clean = re.sub(r'\s+', ' ', l_clean)
                    
                    parts = l_clean.split()
                    if len(parts) >= 2:
                        rows.append({
                            "Date": s_date, "Cours": c_name, "Heure": h_deb,
                            "Nom": parts[0].upper(), 
                            "Prenom": " ".join(parts[1:]),
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
        st.success("✅ Appel enregistré !")
        if st.button("Faire un nouvel appel"):
            st.session_state.clear()
            st.rerun()
        return

    up = st.file_uploader("Charger le PDF d'appel", type=["pdf"])
    if up:
        if 'df_appel' not in st.session_state:
            st.session_state.df_appel = parse_pdf_complete(up.read())

        df = st.session_state.df_appel
        if df.empty:
            st.error("Erreur de lecture du PDF.")
            return

        # Affichage Jour + Date
        d_obj = df['Date'].iloc[0]
        jours_fr = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
        date_complete = f"{jours_fr[d_obj.weekday()]} {d_obj.strftime('%d/%m/%Y')}"
        st.info(f"📅 **{date_complete}** | {df['Cours'].iloc[0]} à {df['Heure'].iloc[0]}")

        # --- ACTIONS RAPIDES (CORRIGÉES V4.4) ---
        c1, c2, c3 = st.columns([1, 1, 1])
        if c1.button("✅ TOUT PRÉSENT", use_container_width=True):
            for i in range(len(df)):
                st.session_state[f"cb_{i}"] = True # Force l'état du widget
            st.rerun()
            
        if c2.button("❌ TOUT ABSENT", use_container_width=True):
            for i in range(len(df)):
                st.session_state[f"cb_{i}"] = False # Force l'état du widget
            st.rerun()
            
        c3.markdown("<p style='text-align:center;'><a href='#bottom'>⬇️ Aller au résumé</a></p>", unsafe_allow_html=True)

        st.write("---")

        # --- LISTE DES ÉLÈVES ---
        for idx, row in df.iterrows():
            key = f"cb_{idx}"
            # Initialisation de l'état si première fois
            if key not in st.session_state:
                st.session_state[key] = False
            
            # Couleur basée sur l'état réel de la case
            bg = "#dcfce7" if st.session_state[key] else "#fee2e2"
            col_n, col_c = st.columns([4, 1])
            
            col_n.markdown(f"""
                <div style='padding:12px; background:{bg}; color:black; border-radius:8px; margin-bottom:5px; border:1px solid #ccc;'>
                    <strong>{row['Nom']} {row['Prenom']}</strong>
                </div>
            """, unsafe_allow_html=True)
            
            # Le widget est lié à la clé dans session_state
            st.checkbox("P", key=key, label_visibility="collapsed")
            # Mise à jour de la colonne Absent pour le résumé et le Cloud
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
    s = st.text_input("🔎 Nom")
    if s and not df_all.empty:
        res = df_all[df_all["Nom"].str.contains(s, case=False, na=False) | df_all["Prenom"].str.contains(s, case=False, na=False)]
        st.dataframe(res[["Date", "Cours", "Absent"]].sort_values("Date", ascending=False), use_container_width=True)

def show_manager():
    st.title("📊 Manager")
    if st.text_input("Code", type="password") == MANAGER_PASSWORD:
        if df_all.empty: return
        today = pd.Timestamp.now().normalize()
        df_p = df_all[df_all["Absent"] == False]
        if not df_p.empty:
            last_v = df_p.groupby(["Nom", "Prenom"])["Date_dt"].max().reset_index()
            last_v["Absence"] = (today - last_v["Date_dt"]).dt.days
            st.dataframe(last_v[last_v["Absence"] > 21].sort_values("Absence", ascending=False), use_container_width=True)

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

import streamlit as st
import pandas as pd
import pdfplumber
import re
import io
from datetime import datetime, date
from streamlit_gsheets import GSheetsConnection

# =======================
# 1. CONFIGURATION
# =======================
st.set_page_config(page_title="Piscine Pro - Full", layout="wide", page_icon="🏊‍♂️")

MANAGER_PASSWORD = st.secrets.get("MANAGER_PASSWORD", "manager")

try:
    conn = st.connection("gsheets", type=GSheetsConnection)
    df_all = conn.read(ttl=0)
    if not df_all.empty:
        df_all["Date_dt"] = pd.to_datetime(df_all["Date"], dayfirst=True, errors='coerce')
except:
    df_all = pd.DataFrame()

# =======================
# 2. FONCTIONS DE SAUVEGARDE & PDF
# =======================
def save_data_to_cloud(df_new):
    existing_data = conn.read(ttl=0)
    df_new["Date"] = pd.to_datetime(df_new["Date"]).dt.strftime('%d/%m/%Y')
    updated_data = pd.concat([existing_data, df_new], ignore_index=True)
    conn.update(data=updated_data)

def parse_pdf_complete(file_bytes):
    rows = []
    # --- FILTRE DES LIGNES INUTILES (Photo 15) ---
    ignore_list = ["TCPDF", "places", "réservées", "disponibles", "ouvertes", "le ", " à "]
    
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for idx, page in enumerate(pdf.pages):
                txt = page.extract_text()
                if not txt: continue
                lines = txt.splitlines()
                
                # Extraction Date/Cours/Heure
                d_str = ""
                for l in lines[:10]:
                    m = re.search(r"\d{2}/\d{2}/\d{4}", l)
                    if m: d_str = m.group(0); break
                s_date = datetime.strptime(d_str, "%d/%m/%Y").date() if d_str else date.today()
                
                c_name, h_deb = "Cours", "00h00"
                for l in lines[:10]:
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
                    # On ignore les lignes vides ou contenant les mots interdits
                    if not l.strip() or any(x in l for x in ignore_list):
                        continue
                        
                    parts = l.split()
                    if len(parts) >= 3:
                        rows.append({
                            "Date": s_date, "Cours": c_name, "Heure": h_deb,
                            "Nom": parts[-1], "Prenom": " ".join(parts[1:-1]),
                            "Absent": False, "Manuel": False, "Session_ID": f"{s_date}_{h_deb}_{idx}"
                        })
    except: pass
    return pd.DataFrame(rows)

# =======================
# 3. INTERFACE MAÎTRE-NAGEUR
# =======================
def show_maitre_nageur():
    st.markdown("<div id='top'></div>", unsafe_allow_html=True) # Ancre pour remonter
    st.title("👨‍🏫 Appel Bassin")
    
    if st.session_state.get("appel_termine", False):
        st.success("✅ Appel envoyé !")
        if st.button("Nouvel appel"):
            st.session_state.clear()
            st.rerun()
        return

    up = st.file_uploader("Charger le PDF", type=["pdf"])
    if up:
        if 'df_appel' not in st.session_state:
            st.session_state.df_appel = parse_pdf_complete(up.read())

        df = st.session_state.df_appel
        st.info(f"📅 {df['Cours'].iloc[0]} à {df['Heure'].iloc[0]}")

        # --- BOUTONS DE NAVIGATION & ACTIONS RAPIDES ---
        c_nav1, c_nav2, c_nav3 = st.columns([1, 1, 1])
        if c_nav1.button("✅ TOUT PRÉSENT"):
            for i in range(len(df)): st.session_state[f"pres_{i}"] = True
            st.rerun()
        if c_nav2.button("❌ TOUT ABSENT"):
            for i in range(len(df)): st.session_state[f"pres_{i}"] = False
            st.rerun()
        c_nav3.markdown("[⬇️ Aller au résumé](#bottom)", unsafe_allow_html=True)

        st.write("---")

        # Liste des élèves
        for idx, row in df.iterrows():
            key = f"pres_{idx}"
            if key not in st.session_state: st.session_state[key] = False
            
            bg = "#dcfce7" if st.session_state[key] else "#fee2e2"
            col_n, col_c = st.columns([4, 1])
            
            col_n.markdown(f"""
                <div style='padding:12px; background:{bg}; color:black; border-radius:8px; margin-bottom:5px; border:1px solid #ccc;'>
                    <strong>{row['Nom'].upper()} {row['Prenom']}</strong>
                </div>
            """, unsafe_allow_html=True)
            
            st.session_state[key] = col_c.checkbox("P", key=f"cb_{idx}", value=st.session_state[key], label_visibility="collapsed")
            df.at[idx, "Absent"] = not st.session_state[key]

        st.markdown("<div id='bottom'></div>", unsafe_allow_html=True) # Ancre pour descendre
        st.write("---")
        
        # Résumé
        presents = len(df[df["Absent"] == False])
        st.subheader("📋 Résumé de l'appel")
        r1, r2, r3 = st.columns(3)
        r1.metric("Inscrits", len(df))
        r2.metric("Absents", len(df) - presents, delta_color="inverse")
        r3.metric("DANS L'EAU", presents)

        if st.button("💾 ENREGISTRER DÉFINITIVEMENT", type="primary", use_container_width=True):
            save_data_to_cloud(df)
            st.session_state.appel_termine = True
            st.rerun()
        
        st.markdown("[⬆️ Remonter en haut](#top)", unsafe_allow_html=True)

# =======================
# 4. AUTRES PAGES & ROUTAGE
# =======================
def show_reception():
    st.title("💁 Réception")
    s = st.text_input("🔎 Nom de l'adhérent")
    if s and not df_all.empty:
        res = df_all[df_all["Nom"].str.contains(s, case=False, na=False)]
        st.dataframe(res[["Date", "Cours", "Absent"]])

def show_manager():
    st.title("📊 Manager")
    if st.text_input("Code", type="password") == MANAGER_PASSWORD:
        st.write("Statistiques bientôt disponibles...")

def show_main_hub():
    st.markdown("<h1 style='text-align: center;'>🏊‍♂️ Piscine Pro</h1>", unsafe_allow_html=True)
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

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

# Mots de passe
MANAGER_PASSWORD = st.secrets.get("MANAGER_PASSWORD", "manager")

# Connexion Google Sheets
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
    # Nettoyage des lignes inutiles
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
                    
                    # --- CORRECTION DES NUMÉROS (V4.2) ---
                    parts = l.split()
                    # On garde uniquement les mots qui ne sont pas des nombres purs (ex: on retire 11074145)
                    clean_parts = [p for p in parts if not p.isdigit()]
                    
                    if len(clean_parts) >= 2:
                        # On considère le premier mot comme le NOM et le reste comme le Prénom
                        rows.append({
                            "Date": s_date, "Cours": c_name, "Heure": h_deb,
                            "Nom": clean_parts[0], 
                            "Prenom": " ".join(clean_parts[1:]),
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
        st.success("✅ Appel envoyé !")
        if st.button("Faire un nouvel appel"):
            st.session_state.clear()
            st.rerun()
        return

    up = st.file_uploader("Charger la feuille d'appel PDF", type=["pdf"])
    if up:
        if 'df_appel' not in st.session_state:
            st.session_state.df_appel = parse_pdf_complete(up.read())

        df = st.session_state.df_appel
        if df.empty:
            st.error("Aucun élève trouvé. Vérifiez le PDF.")
            return

        # Affichage Jour + Date
        d_obj = df['Date'].iloc[0]
        jours_fr = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
        try:
            date_complete = f"{jours_fr[d_obj.weekday()]} {d_obj.strftime('%d/%m/%Y')}"
        except:
            date_complete = str(d_obj)

        st.info(f"📅 **{date_complete}** | {df['Cours'].iloc[0]} à {df['Heure'].iloc[0]}")

        # Actions rapides
        c_nav1, c_nav2, c_nav3 = st.columns([1, 1, 1])
        if c_nav1.button("✅ TOUT PRÉSENT", use_container_width=True):
            for i in range(len(df)): st.session_state[f"pres_{i}"] = True
            st.rerun()
        if c_nav2.button("❌ TOUT ABSENT", use_container_width=True):
            for i in range(len(df)): st.session_state[f"pres_{i}"] = False
            st.rerun()
        c_nav3.markdown("<p style='text-align:center;'><a href='#bottom'>⬇️ Aller au résumé</a></p>", unsafe_allow_html=True)

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

        # Ajout manuel
        st.write("---")
        with st.expander("➕ AJOUTER UN ÉLÈVE HORS PDF"):
            with st.form("form_ajout", clear_on_submit=True):
                nom_m = st.text_input("Nom").upper()
                prenom_m = st.text_input("Prénom")
                if st.form_submit_button("Valider l'ajout"):
                    if nom_m and prenom_m:
                        nouveau_row = {
                            "Date": df['Date'].iloc[0], "Cours": df['Cours'].iloc[0], "Heure": df['Heure'].iloc[0],
                            "Nom": nom_m, "Prenom": prenom_m, "Absent": False, "Manuel": True, "Session_ID": df['Session_ID'].iloc[0]
                        }
                        st.session_state.df_appel = pd.concat([df, pd.DataFrame([nouveau_row])], ignore_index=True)
                        st.rerun()

        st.markdown("<div id='bottom'></div>", unsafe_allow_html=True)
        st.write("---")
        
        # Résumé
        presents = len(df[df["Absent"] == False])
        st.subheader("📋 Résumé de l'appel")
        r1, r2, r3 = st.columns(3)
        r1.metric("Inscrits PDF", len(df[df["Manuel"]==False]))
        r2.metric("Absents", len(df[df["Absent"]==True]), delta_color="inverse")
        r3.metric("TOTAL DANS L'EAU", presents)

        if st.button("💾 ENREGISTRER DÉFINITIVEMENT", type="primary", use_container_width=True):
            save_data_to_cloud(df)
            st.session_state.appel_termine = True
            st.rerun()
        
        st.markdown("<p style='text-align:center;'><a href='#top'>⬆️ Remonter en haut</a></p>", unsafe_allow_html=True)

# =======================
# 4. RÉCEPTION & MANAGER
# =======================
def show_reception():
    st.title("💁 Réception - Recherche")
    s = st.text_input("🔎 Entrez le nom de l'adhérent")
    if s and not df_all.empty:
        res = df_all[df_all["Nom"].str.contains(s, case=False, na=False) | df_all["Prenom"].str.contains(s, case=False, na=False)]
        st.dataframe(res[["Date", "Cours", "Absent"]].sort_values("Date", ascending=False), use_container_width=True)

def show_manager():
    st.title("📊 Espace Manager")
    if st.text_input("Code d'accès", type="password") == MANAGER_PASSWORD:
        if df_all.empty: return
        today = pd.Timestamp.now().normalize()
        df_p = df_all[df_all["Absent"] == False]
        if not df_p.empty:
            last_v = df_p.groupby(["Nom", "Prenom"])["Date_dt"].max().reset_index()
            last_v["Jours_absence"] = (today - last_v["Date_dt"]).dt.days
            risk = last_v[last_v["Jours_absence"] > 21].sort_values("Jours_absence", ascending=False)
            st.dataframe(risk, use_container_width=True)

# =======================
# 5. HUB D'ACCUEIL
# =======================
def show_main_hub():
    st.markdown("<h1 style='text-align: center;'>🏊‍♂️ Application Piscine Pro</h1>", unsafe_allow_html=True)
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

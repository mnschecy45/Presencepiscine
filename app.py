import streamlit as st
import pandas as pd
import pdfplumber
import re
import io
import altair as alt
from datetime import datetime, date
from pyairtable import Api

# =======================
# 0. VOS CLES AIRTABLE
# =======================
API_TOKEN = "pat85co2rWjG48EDz.e6e628e1b5da543271388625e0006a0186a2e424ff7a3ae6e146508794f8edbd"
BASE_ID = "app390ytx6oa2rbge"
TABLE_NAME = "Presences"

# =======================
# 1. CONFIGURATION & STYLE CSS
# =======================
st.set_page_config(page_title="Piscine Pro", layout="wide", page_icon="🏊‍♂️")

st.markdown("""
    <style>
    /* 1. Style pour PRÉSENT (Vert foncé - Texte Blanc) */
    .student-box-present {
        background-color: #1b5e20;
        color: white;
        padding: 15px;
        border-radius: 8px;
        font-weight: bold;
        font-size: 16px;
        margin-bottom: 5px;
        text-align: center;
        border: 1px solid #144a17;
    }
    
    /* 2. Style pour ABSENT (Rouge vif - Texte Blanc) */
    .student-box-absent {
        background-color: #b71c1c; 
        color: white;
        padding: 15px;
        border-radius: 8px;
        font-weight: bold;
        font-size: 16px;
        margin-bottom: 5px;
        text-align: center;
        border: 1px solid #7f0000;
    }

    /* 3. Checkbox centré verticalement */
    .stCheckbox {
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100%;
        padding-top: 10px;
    }

    /* 4. Footer Fixe (Bandeau noir en bas) */
    .fixed-footer {
        position: fixed;
        bottom: 0;
        left: 0;
        width: 100%;
        background-color: #1e1e1e;
        padding: 10px 0;
        border-top: 3px solid #4CAF50;
        z-index: 9990;
        box-shadow: 0px -2px 10px rgba(0,0,0,0.5);
        color: white;
        font-family: sans-serif;
    }
    
    .footer-content {
        display: flex; 
        justify-content: space-around; 
        align-items: center; 
        max-width: 800px; 
        margin: 0 auto;
    }

    .footer-stat { text-align: center; }
    .footer-stat-val { font-size: 1.2rem; font-weight: bold; }
    .footer-stat-label { font-size: 0.7rem; opacity: 0.8; text-transform: uppercase; }

    /* 5. Marge en bas pour ne pas cacher le dernier élève derrière le footer */
    .block-container {
        padding-bottom: 150px;
    }
    </style>
""", unsafe_allow_html=True)

MANAGER_PASSWORD = st.secrets.get("MANAGER_PASSWORD", "manager")

# --- CONNEXION AIRTABLE ---
try:
    api = Api(API_TOKEN)
    table = api.table(BASE_ID, TABLE_NAME)
    records = table.all()
    if records:
        data = []
        for r in records:
            row = r['fields']
            row['id'] = r['id']
            data.append(row)
        df_all = pd.DataFrame(data)
        if "Date" in df_all.columns:
            df_all["Date_dt"] = pd.to_datetime(df_all["Date"], errors='coerce')
    else:
        df_all = pd.DataFrame()
except Exception as e:
    st.error(f"Erreur connexion : {e}")
    df_all = pd.DataFrame()

# =======================
# 2. FONCTIONS UTILES (LOGIQUE METIER)
# =======================

def delete_previous_session_records(date_val, heure_val, cours_val):
    """Supprime les enregistrements existants pour ce créneau précis avant de resauvegarder"""
    if df_all.empty: return
    
    date_str = date_val.strftime("%Y-%m-%d") if isinstance(date_val, (date, datetime)) else str(date_val)
    
    mask = (
        (df_all["Date"] == date_str) & 
        (df_all["Heure"] == heure_val) & 
        (df_all["Cours"] == cours_val)
    )
    to_delete = df_all[mask]
    
    if not to_delete.empty:
        ids = to_delete['id'].tolist()
        for i in range(0, len(ids), 10):
            table.batch_delete(ids[i:i+10])
            
def save_data_to_cloud(df_new):
    """Sauvegarde en mode 'Ecraser et Remplacer'"""
    # 1. Infos du cours
    first_row = df_new.iloc[0]
    d_val = first_row["Date"]
    h_val = first_row["Heure"]
    c_val = first_row["Cours"]
    
    # 2. Nettoyage ancien appel
    with st.spinner("Mise à jour de l'appel..."):
        delete_previous_session_records(d_val, h_val, c_val)
    
    # 3. Création nouveaux records
    prog = st.progress(0)
    total = len(df_new)
    for i, row in df_new.iterrows():
        try:
            statut = "Absent" if row["Absent"] else "Présent"
            d_str = row["Date"].strftime("%Y-%m-%d") if isinstance(row["Date"], (date, datetime)) else str(row["Date"])
            rec = {
                "Nom": str(row["Nom"]),
                "Statut": statut,
                "Date": d_str,
                "Cours": str(row["Cours"]),
                "Heure": str(row["Heure"]),
                "Traite": False
            }
            table.create(rec)
            prog.progress((i + 1) / total)
        except: pass
    prog.empty()
    st.toast("C'est enregistré !", icon="💾")

def parse_pdf_complete(file_bytes):
    rows = []
    ign = ["TCPDF", "www.", "places", "réservées", "disponibles", "ouvertes", "le ", " à ", "Page ", "Généré"]
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
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
                start = 0
                for i, l in enumerate(lines):
                    if "N° réservation" in l: start = i + 1; break
                for l in lines[start:]:
                    if not l.strip() or any(x in l for x in ign): continue
                    lc = re.sub(r'\d+', '', l).strip()
                    p = lc.split()
                    if len(p) >= 2:
                        rows.append({
                            "Date": s_date, "Cours": c_name, "Heure": h_deb,
                            "Nom": p[0].upper(), "Prenom": " ".join(p[1:]),
                            "Absent": False, "Manuel": False, "Session_ID": f"{s_date}_{h_deb}"
                        })
    except: pass
    return pd.DataFrame(rows)

# =======================
# 3. MAÎTRE-NAGEUR (INTERFACE COMPLETE)
# =======================
def show_maitre_nageur():
    st.title("👨‍🏫 Appel Bassin")
    
    # --- ECRAN SUCCES ---
    if st.session_state.get("appel_termine", False):
        st.success("✅ Appel mis à jour avec succès !")
        if st.button("Retour à l'accueil"):
            st.session_state.appel_termine = False
            if 'df_appel' in st.session_state: del st.session_state.df_appel
            if 'current_file' in st.session_state: del st.session_state.current_file
            # Reset checkbox keys
            for k in list(st.session_state.keys()):
                if k.startswith("cb_"): del st.session_state[k]
            st.rerun()
        return

    # --- ZONE 1 : REPRISE RAPIDE (RETARDATAIRES) ---
    # On regarde si on a des cours dans la base pour proposer des boutons
    if not df_all.empty and 'df_appel' not in st.session_state:
        # Création d'une vue unique des sessions (Date + Heure + Cours)
        df_unique = df_all.drop_duplicates(subset=['Date', 'Heure', 'Cours']).copy()
        if "Date_dt" in df_unique.columns:
            df_unique = df_unique.sort_values("Date_dt", ascending=False)
        
        # On prend les 3 derniers cours
        recent_sessions = df_unique.head(3) 
        
        if not recent_sessions.empty:
            st.subheader("🔄 Reprendre un appel (Retardataires)")
            cols = st.columns(len(recent_sessions))
            
            for i, (_, row_sess) in enumerate(recent_sessions.iterrows()):
                d_txt = row_sess['Date']
                h_txt = row_sess['Heure']
                c_txt = row_sess['Cours']
                label_btn = f"{c_txt}\n{d_txt} à {h_txt}"
                
                if cols[i].button(label_btn, key=f"hist_{i}", use_container_width=True):
                    # ACTION : On recharge depuis la base
                    mask = (df_all["Date"] == row_sess['Date']) & \
                           (df_all["Heure"] == row_sess['Heure']) & \
                           (df_all["Cours"] == row_sess['Cours'])
                    session_data = df_all[mask].copy()
                    
                    reconstructed_rows = []
                    for _, r in session_data.iterrows():
                        reconstructed_rows.append({
                            "Date": r['Date'],
                            "Cours": r['Cours'],
                            "Heure": r['Heure'],
                            "Nom": str(r['Nom']), 
                            "Prenom": "", 
                            "Absent": (r['Statut'] == "Absent"),
                            "Manuel": False,
                            "Session_ID": f"{r['Date']}_{r['Heure']}"
                        })
                    
                    st.session_state.df_appel = pd.DataFrame(reconstructed_rows)
                    st.session_state["mode_retard"] = True # On active le mode retardataire direct
                    
                    # On pré-coche les cases (Si Absent=False -> Checkbox=True)
                    for idx, row in st.session_state.df_appel.iterrows():
                        st.session_state[f"cb_{idx}"] = not row["Absent"] 
                    
                    st.rerun()

    # --- ZONE 2 : UPLOAD PDF ---
    if 'df_appel' not in st.session_state:
        st.write("---")
        st.write("#### 📂 Ou commencer un nouvel appel")
        up = st.file_uploader("Glisser le PDF ici", type=["pdf"])
        
        if up:
            st.session_state.current_file = up.name
            st.session_state.df_appel = parse_pdf_complete(up.read())
            # Reset checkbox keys
            for k in list(st.session_state.keys()):
                 if k.startswith("cb_"): del st.session_state[k]
            st.rerun()

    # --- ZONE 3 : LA LISTE D'APPEL ---
    if 'df_appel' in st.session_state:
        df = st.session_state.df_appel
        if not df.empty:
            # Infos
            row1 = df.iloc[0]
            d_aff = row1['Date']
            if isinstance(d_aff, (date, datetime)): d_aff = d_aff.strftime('%d/%m/%Y')
            
            st.markdown(f"### 📅 {d_aff} | {row1['Cours']} ({row1['Heure']})")
            
            # Boutons globaux
            c1, c2 = st.columns(2)
            if c1.button("✅ TOUT PRÉSENT", use_container_width=True):
                for i in range(len(df)): st.session_state[f"cb_{i}"] = True
                st.rerun()
            if c2.button("❌ TOUT ABSENT", use_container_width=True):
                for i in range(len(df)): st.session_state[f"cb_{i}"] = False
                st.rerun()

            st.write("---")
            
            # Toggle Retardataire
            if "mode_retard" not in st.session_state: st.session_state["mode_retard"] = False
            mode_retard = st.toggle("🕒 Mode Retardataires (Masquer les présents déjà validés)", key="toggle_retard")
            
            # La boucle d'affichage des élèves
            for idx, row in df.iterrows():
                k = f"cb_{idx}"
                # Init checkbox si elle n'existe pas
                if k not in st.session_state: st.session_state[k] = not row["Absent"]
                
                # Masquage dynamique
                if mode_retard and st.session_state[k]:
                    continue
                
                # Layout
                col_check, col_name = st.columns([1, 4])
                with col_check:
                    st.checkbox("P", key=k, label_visibility="collapsed")
                
                with col_name:
                    nom_complet = f"{row['Nom']} {row['Prenom']}".strip()
                    if st.session_state[k]:
                        st.markdown(f'<div class="student-box-present">{nom_complet}</div>', unsafe_allow_html=True)
                    else:
                        st.markdown(f'<div class="student-box-absent">{nom_complet}</div>', unsafe_allow_html=True)
                
                # Update DF
                df.at[idx, "Absent"] = not st.session_state[k]

            # Ajout manuel
            st.write("---")
            with st.expander("➕ Ajouter un élève manuellement"):
                with st.form("add"):
                    nm = st.text_input("Nom").upper()
                    if st.form_submit_button("Ajouter"):
                        nr = df.iloc[0].copy()
                        nr["Nom"] = nm; nr["Prenom"] = "(Manuel)"; nr["Manuel"] = True; nr["Absent"] = False
                        st.session_state.df_appel = pd.concat([df, pd.DataFrame([nr])], ignore_index=True)
                        new_idx = len(st.session_state.df_appel) - 1
                        st.session_state[f"cb_{new_idx}"] = True
                        st.rerun()

            # --- FOOTER FIXE ---
            nb_present = len(df[df["Absent"] == False])
            nb_absent = len(df[df["Absent"] == True])
            nb_total = len(df)
            
            st.markdown(f"""
            <div class="fixed-footer">
                <div class="footer-content">
                    <div class="footer-stat"><div class="footer-stat-val">{nb_total}</div><div class="footer-stat-label">TOTAL</div></div>
                    <div class="footer-stat" style="color: #4CAF50;"><div class="footer-stat-val">{nb_present}</div><div class="footer-stat-label">PRÉSENTS</div></div>
                    <div class="footer-stat" style="color: #f44336;"><div class="footer-stat-val">{nb_absent}</div><div class="footer-stat-label">ABSENTS</div></div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # Bouton Valider (Streamlit Button)
            if st.button(f"💾 SAUVEGARDER L'APPEL", type="primary", use_container_width=True):
                save_data_to_cloud(df)
                st.session_state.appel_termine = True
                st.rerun()

# =======================
# 4. RÉCEPTION (STANDARD)
# =======================
def show_reception():
    st.title("💁 Réception")
    if df_all.empty: return

    df_w = df_all.copy()
    if "Date_dt" not in df_w.columns and "Date" in df_w.columns:
         df_w["Date_dt"] = pd.to_datetime(df_w["Date"], errors='coerce')
    if "Traite" not in df_w.columns: df_w["Traite"] = False
    if "Prenom" not in df_w.columns: df_w["Prenom"] = ""

    t1, t2, t3 = st.tabs(["⚡ ABSENCES", "⚠️ NON INSCRITS", "✅ HISTORIQUE"])

    with t1:
        todo = df_w[(df_w["Statut"] == "Absent") & (df_w["Traite"] != True) & (df_w["Prenom"] != "(Manuel)")]
        if todo.empty: st.success("Aucune absence à traiter.")
        else:
            st.write(f"**{len(todo)} absences en attente**")
            cli = st.selectbox("Client", todo["Nom"].unique())
            if cli:
                tot_abs = len(df_w[(df_w["Nom"] == cli) & (df_w["Statut"] == "Absent")])
                s1, s2, s3 = 1, 3, 5
                
                niv = 1
                if tot_abs >= s3: niv=3
                elif tot_abs >= s2: niv=2
                
                color = "🔴" if niv==3 else "🟠" if niv==2 else "🟡"
                st.markdown(f"### {color} NIVEAU {niv} ({tot_abs} abs)")

                sub = todo[todo["Nom"] == cli]
                ids = sub['id'].tolist()
                
                if st.button("✅ Marquer comme traité", type="primary"):
                    now = datetime.now().strftime("%Y-%m-%d %H:%M")
                    for pid in ids:
                        try: table.update(pid, {"Traite": True, "Date_Traitement": now})
                        except: pass
                    st.success("Traité !")
                    st.rerun()

    with t2:
        manuels = df_w[(df_w["Prenom"] == "(Manuel)") & (df_w["Traite"] != True)]
        if manuels.empty: st.success("R.A.S")
        else:
            st.warning(f"{len(manuels)} non-inscrits")
            cli_man = st.selectbox("Client", manuels["Nom"].unique())
            if cli_man:
                sub_m = manuels[manuels["Nom"] == cli_man]
                ids_m = sub_m['id'].tolist()
                if st.button("✅ Régularisé"):
                    now = datetime.now().strftime("%Y-%m-%d %H:%M")
                    for pid in ids_m:
                        try: table.update(pid, {"Traite": True, "Date_Traitement": now})
                        except: pass
                    st.rerun()

    with t3:
        done = df_w[df_w["Traite"] == True]
        st.dataframe(done, use_container_width=True)

# =======================
# 5. MANAGER (STANDARD)
# =======================
def show_manager():
    st.title("📊 Manager")
    if st.sidebar.text_input("Mdp", type="password") != MANAGER_PASSWORD:
        st.warning("Accès refusé"); return
    
    if not df_all.empty:
        tot = len(df_all)
        pres = len(df_all[df_all["Statut"]=="Présent"])
        taux = (pres/tot*100) if tot > 0 else 0
        st.metric("Taux de présence global", f"{taux:.1f}%")
        st.dataframe(df_all)
    
    if st.checkbox("Activer suppression"):
        if st.button("🔥 VIDER LA BASE", type="primary"):
            ids = [r['id'] for r in table.all()]
            for i in range(0, len(ids), 10):
                table.batch_delete(ids[i:i+10])
            st.success("Base vidée.")
            st.rerun()

# =======================
# 6. ROUTER (NAVIGATION)
# =======================
if 'page' not in st.session_state: st.session_state.page = "HUB"
def go(p): st.session_state.page = p; st.rerun()

if st.session_state.page == "HUB":
    st.title("🏊‍♂️ Piscine Pro")
    c1, c2, c3 = st.columns(3)
    if c1.button("MAÎTRE-NAGEUR", use_container_width=True): go("MN")
    if c2.button("RÉCEPTION", use_container_width=True): go("REC")
    if c3.button("MANAGER", use_container_width=True): go("MGR")
elif st.session_state.page == "MN":
    if st.sidebar.button("🏠 ACCUEIL"): go("HUB")
    show_maitre_nageur()
elif st.session_state.page == "REC":
    if st.sidebar.button("🏠 ACCUEIL"): go("HUB")
    show_reception()
elif st.session_state.page == "MGR":
    if st.sidebar.button("🏠 ACCUEIL"): go("HUB")
    show_manager()

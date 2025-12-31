import streamlit as st
import pandas as pd
import pdfplumber
import re
import io
import time
from datetime import datetime, date
from pyairtable import Api

# =======================
# 1. CONFIGURATION INITIALE
# =======================
st.set_page_config(page_title="Piscine Pro", layout="wide", page_icon="🏊‍♂️")

# VOS CLES AIRTABLE
API_TOKEN = "pat85co2rWjG48EDz.e6e628e1b5da543271388625e0006a0186a2e424ff7a3ae6e146508794f8edbd"
BASE_ID = "app390ytx6oa2rbge"
TABLE_NAME = "Presences"
MANAGER_PASSWORD = st.secrets.get("MANAGER_PASSWORD", "manager")

# --- STYLE CSS (Couleurs Vives + Footer) ---
st.markdown("""
    <style>
    /* PRÉSENT : Vert Foncé / Texte Blanc */
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
    
    /* ABSENT : Rouge Vif / Texte Blanc */
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

    /* Checkbox centré */
    .stCheckbox {
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100%;
        padding-top: 10px;
    }

    /* Footer Fixe */
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

    /* Marge bas de page */
    .block-container { padding-bottom: 150px; }
    </style>
""", unsafe_allow_html=True)

# =======================
# 2. CHARGEMENT DONNÉES
# =======================
@st.cache_data(ttl=10) # Cache court pour voir les modifs vite
def load_airtable_data():
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
            df = pd.DataFrame(data)
            if "Date" in df.columns:
                df["Date_dt"] = pd.to_datetime(df["Date"], errors='coerce')
            return df, table
        return pd.DataFrame(), table
    except Exception as e:
        return pd.DataFrame(), None

df_all, airtable_table = load_airtable_data()

# =======================
# 3. FONCTIONS LOGIQUES
# =======================

def delete_previous_session_records(date_val, heure_val, cours_val):
    if df_all.empty or airtable_table is None: return
    date_str = date_val.strftime("%Y-%m-%d") if isinstance(date_val, (date, datetime)) else str(date_val)
    mask = (df_all["Date"] == date_str) & (df_all["Heure"] == heure_val) & (df_all["Cours"] == cours_val)
    to_delete = df_all[mask]
    if not to_delete.empty:
        ids = to_delete['id'].tolist()
        for i in range(0, len(ids), 10):
            airtable_table.batch_delete(ids[i:i+10])
            
def save_data_to_cloud(df_new):
    if airtable_table is None:
        st.error("Erreur connexion Airtable"); return

    first_row = df_new.iloc[0]
    d_val = first_row["Date"]; h_val = first_row["Heure"]; c_val = first_row["Cours"]
    
    # 1. Nettoyage
    with st.spinner("Mise à jour de l'appel..."):
        delete_previous_session_records(d_val, h_val, c_val)
    
    # 2. Sauvegarde
    prog = st.progress(0); total = len(df_new)
    for i, row in df_new.iterrows():
        try:
            statut = "Absent" if row["Absent"] else "Présent"
            d_str = row["Date"].strftime("%Y-%m-%d") if isinstance(row["Date"], (date, datetime)) else str(row["Date"])
            rec = {
                "Nom": str(row["Nom"]), "Statut": statut, "Date": d_str,
                "Cours": str(row["Cours"]), "Heure": str(row["Heure"]), "Traite": False
            }
            airtable_table.create(rec)
            prog.progress((i + 1) / total)
        except: pass
    prog.empty()
    
    # 3. MEMORISATION IMMEDIATE DU COURS ACTUEL
    st.session_state['latest_course_context'] = {
        'Date': d_val,
        'Heure': h_val,
        'Cours': c_val
    }
    
    st.toast("C'est enregistré !", icon="💾")
    load_airtable_data.clear() # Force le rechargement de la base au prochain passage

def parse_pdf_complete(file_bytes):
    rows = []
    ign = ["TCPDF", "www.", "places", "réservées", "disponibles", "ouvertes", "le ", " à ", "Page ", "Généré"]
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                txt = page.extract_text()
                if not txt: continue
                lines = txt.splitlines()
                d_str = ""; c_name = "Cours Inconnu"; h_deb = "00h00"
                
                for l in lines[:15]:
                    m = re.search(r"\d{2}/\d{2}/\d{4}", l)
                    if m: d_str = m.group(0); break
                s_date = datetime.strptime(d_str, "%d/%m/%Y").date() if d_str else date.today()
                
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
# 4. PAGE MAÎTRE-NAGEUR
# =======================
def show_maitre_nageur():
    st.title("👨‍🏫 Appel Bassin")

    # Si appel terminé
    if st.session_state.get("appel_termine", False):
        st.success("✅ Appel mis à jour avec succès !")
        if st.button("Retour à l'accueil"):
            st.session_state.appel_termine = False
            for k in ['df_appel', 'current_file']:
                if k in st.session_state: del st.session_state[k]
            for k in list(st.session_state.keys()):
                if k.startswith("cb_"): del st.session_state[k]
            st.rerun()
        return

    # --- PARTIE 1 : BOUTON UNIQUE "DERNIER APPEL" ---
    # Logique : Soit on a un appel qu'on vient de faire (session), soit on prend le dernier en date (DB)
    
    target_course = None
    
    # Cas A : On vient juste de sauvegarder un cours (Priorité absolue)
    if 'latest_course_context' in st.session_state:
        target_course = st.session_state['latest_course_context']
    
    # Cas B : Sinon, on cherche le dernier dans la base Airtable
    elif not df_all.empty and "Date_dt" in df_all.columns:
        df_sorted = df_all.sort_values(["Date_dt", "Heure"], ascending=[False, False])
        df_last = df_sorted.drop_duplicates(subset=['Date', 'Heure', 'Cours']).head(1)
        if not df_last.empty:
            last_row = df_last.iloc[0]
            target_course = {
                'Date': last_row['Date'],
                'Heure': last_row['Heure'],
                'Cours': last_row['Cours']
            }

    if 'df_appel' not in st.session_state and target_course:
        # Affichage du bouton
        d_aff = target_course['Date']
        if isinstance(d_aff, (date, datetime)): d_aff = d_aff.strftime("%d/%m/%Y") # ou le format brut de Airtable
        else: d_aff = str(d_aff) # Securité

        btn_label = f"🔄 REPRENDRE : {target_course['Cours']} ({d_aff} à {target_course['Heure']})"
        
        if st.button(btn_label, type="primary", use_container_width=True):
            # RECHARGEMENT
            # Attention : il faut s'assurer que df_all est à jour si on vient de save
            # On force un petit reload si besoin, mais normalement load_airtable_data le gère
            
            # Re-filtrage sur df_all (même s'il est pas 100% frais, on espère que cache clear a marché)
            # Pour la date, on compare en string pour éviter les soucis de type
            d_target_str = target_course['Date']
            if isinstance(d_target_str, (date, datetime)): d_target_str = d_target_str.strftime("%Y-%m-%d")
            
            # On filtre df_all en convertissant la colonne Date en string pour comparer
            df_all['Date_Str'] = df_all['Date'].apply(lambda x: x.strftime("%Y-%m-%d") if isinstance(x, (date, datetime)) else str(x))
            
            mask = (df_all["Date_Str"] == d_target_str) & \
                   (df_all["Heure"] == target_course['Heure']) & \
                   (df_all["Cours"] == target_course['Cours'])
            
            session_data = df_all[mask].copy()
            
            if session_data.empty:
                st.warning("Données en cours d'écriture... Réessayez dans 5 secondes.")
                load_airtable_data.clear()
            else:
                reconstructed = []
                for _, r in session_data.iterrows():
                    reconstructed.append({
                        "Date": r['Date'], "Cours": r['Cours'], "Heure": r['Heure'],
                        "Nom": str(r['Nom']), "Prenom": "", 
                        "Absent": (r['Statut'] == "Absent"),
                        "Manuel": False
                    })
                
                st.session_state.df_appel = pd.DataFrame(reconstructed)
                st.session_state["mode_retard"] = True # Active mode retardataire
                
                for idx, row in st.session_state.df_appel.iterrows():
                    st.session_state[f"cb_{idx}"] = not row["Absent"]
                    
                st.rerun()

    if 'df_appel' not in st.session_state:
        st.write("---")
        st.markdown("#### 📂 Ou charger un nouveau PDF")
        up = st.file_uploader("Glisser le fichier planning ici", type=["pdf"])
        if up:
            st.session_state.current_file = up.name
            st.session_state.df_appel = parse_pdf_complete(up.read())
            st.session_state["mode_retard"] = False
            # Si on charge un nouveau, on oublie le contexte précédent
            if 'latest_course_context' in st.session_state: del st.session_state['latest_course_context']
            for k in list(st.session_state.keys()):
                 if k.startswith("cb_"): del st.session_state[k]
            st.rerun()

    # --- PARTIE 2 : LISTE D'APPEL ---
    if 'df_appel' in st.session_state:
        df = st.session_state.df_appel
        if not df.empty:
            row1 = df.iloc[0]
            d_show = row1['Date']
            if isinstance(d_show, (date, datetime)): d_show = d_show.strftime('%d/%m/%Y')
            
            st.markdown(f"## 📅 {d_show} | {row1['Cours']} ({row1['Heure']})")
            
            c1, c2 = st.columns(2)
            if c1.button("✅ TOUT PRÉSENT", use_container_width=True):
                for i in range(len(df)): st.session_state[f"cb_{i}"] = True
                st.rerun()
            if c2.button("❌ TOUT ABSENT", use_container_width=True):
                for i in range(len(df)): st.session_state[f"cb_{i}"] = False
                st.rerun()

            st.write("---")
            if "mode_retard" not in st.session_state: st.session_state["mode_retard"] = False
            mode_retard = st.toggle("🕒 Mode Retardataires (Afficher uniquement les absents)", key="toggle_retard", value=st.session_state["mode_retard"])
            
            for idx, row in df.iterrows():
                k = f"cb_{idx}"
                if k not in st.session_state: st.session_state[k] = not row["Absent"]
                
                if mode_retard and st.session_state[k]:
                    continue
                
                c_chk, c_nom = st.columns([1, 4])
                with c_chk:
                    st.checkbox("P", key=k, label_visibility="collapsed")
                with c_nom:
                    full_n = f"{row['Nom']} {row['Prenom']}".strip()
                    if st.session_state[k]:
                        st.markdown(f'<div class="student-box-present">{full_n}</div>', unsafe_allow_html=True)
                    else:
                        st.markdown(f'<div class="student-box-absent">{full_n}</div>', unsafe_allow_html=True)
                
                df.at[idx, "Absent"] = not st.session_state[k]

            st.write("---")
            with st.expander("➕ Ajout Manuel"):
                with st.form("add"):
                    nm = st.text_input("Nom").upper()
                    if st.form_submit_button("Ajouter"):
                        nr = df.iloc[0].copy()
                        nr["Nom"] = nm; nr["Prenom"] = "(Manuel)"; nr["Manuel"] = True; nr["Absent"] = False
                        st.session_state.df_appel = pd.concat([df, pd.DataFrame([nr])], ignore_index=True)
                        new_idx = len(st.session_state.df_appel) - 1
                        st.session_state[f"cb_{new_idx}"] = True
                        st.rerun()

            # Footer
            nb_p = len(df[df["Absent"]==False]); nb_a = len(df[df["Absent"]==True]); nb_t = len(df)
            st.markdown(f"""
            <div class="fixed-footer">
                <div class="footer-content">
                    <div class="footer-stat"><div class="footer-stat-val">{nb_t}</div><div class="footer-stat-label">TOTAL</div></div>
                    <div class="footer-stat" style="color:#4CAF50;"><div class="footer-stat-val">{nb_p}</div><div class="footer-stat-label">PRÉSENTS</div></div>
                    <div class="footer-stat" style="color:#f44336;"><div class="footer-stat-val">{nb_a}</div><div class="footer-stat-label">ABSENTS</div></div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            if st.button("💾 SAUVEGARDER L'APPEL", type="primary", use_container_width=True):
                save_data_to_cloud(df)
                st.session_state.appel_termine = True
                st.rerun()

# =======================
# 5. AUTRES PAGES
# =======================
def show_reception():
    st.title("💁 Réception")
    if df_all.empty: st.info("Aucune donnée."); return
    t1, t2 = st.tabs(["⚡ ABSENCES", "⚠️ NON INSCRITS"])
    with t1:
        todo = df_all[(df_all["Statut"]=="Absent") & (df_all["Traite"]!=True)]
        if todo.empty: st.success("Tout est traité.")
        else:
            cli = st.selectbox("Sélectionner un absent", todo["Nom"].unique())
            if cli:
                sub = todo[todo["Nom"]==cli]
                st.write(f"{len(sub)} absences.")
                if st.button("✅ Marquer Traité", key="t_abs"):
                    for pid in sub['id']: airtable_table.update(pid, {"Traite": True})
                    load_airtable_data.clear()
                    st.rerun()
    with t2:
        mans = df_all[ (df_all["Nom"].astype(str).str.contains("MANUEL") | (df_all.get("Prenom")=="(Manuel)")) & (df_all["Traite"]!=True) ]
        if mans.empty: st.info("RAS")
        else:
            cli_m = st.selectbox("Non Inscrit", mans["Nom"].unique())
            if st.button("✅ Régularisé", key="t_man"):
                sub_m = mans[mans["Nom"]==cli_m]
                for pid in sub_m['id']: airtable_table.update(pid, {"Traite": True})
                load_airtable_data.clear()
                st.rerun()

def show_manager():
    st.title("📊 Manager")
    if st.sidebar.text_input("Mot de passe", type="password") != MANAGER_PASSWORD: return
    st.metric("Total Enregistrements", len(df_all))
    st.dataframe(df_all, use_container_width=True)
    if st.button("🔥 VIDER BASE"):
        ids = [r['id'] for r in airtable_table.all()]
        for i in range(0, len(ids), 10): airtable_table.batch_delete(ids[i:i+10])
        load_airtable_data.clear()
        st.rerun()

# =======================
# 6. ROUTER
# =======================
if 'page' not in st.session_state: st.session_state.page = "HUB"
if st.session_state.page == "HUB":
    st.title("🏊‍♂️ Piscine Pro")
    c1, c2, c3 = st.columns(3)
    if c1.button("MAÎTRE-NAGEUR", use_container_width=True): st.session_state.page="MN"; st.rerun()
    if c2.button("RÉCEPTION", use_container_width=True): st.session_state.page="REC"; st.rerun()
    if c3.button("MANAGER", use_container_width=True): st.session_state.page="MGR"; st.rerun()
else:
    if st.sidebar.button("🏠 ACCUEIL"): st.session_state.page="HUB"; st.rerun()
    if st.session_state.page == "MN": show_maitre_nageur()
    elif st.session_state.page == "REC": show_reception()
    elif st.session_state.page == "MGR": show_manager()

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
# 1. CONFIGURATION & STYLE
# =======================
st.set_page_config(page_title="Piscine Pro", layout="wide", page_icon="🏊‍♂️")

# --- CSS PERSONNALISÉ (COULEURS + FOOTER) ---
st.markdown("""
    <style>
    /* Style pour PRÉSENT (Vert foncé) */
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
    
    /* Style pour ABSENT (Rouge vif) */
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

    /* Checkbox centré verticalement */
    .stCheckbox {
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100%;
        padding-top: 10px;
    }

    /* Footer Fixe en bas de page */
    .fixed-footer {
        position: fixed;
        bottom: 0;
        left: 0;
        width: 100%;
        background-color: #1e1e1e;
        padding: 15px 10px;
        border-top: 3px solid #4CAF50;
        z-index: 9999;
        box-shadow: 0px -2px 10px rgba(0,0,0,0.5);
    }
    
    /* Marge en bas pour ne pas cacher le dernier élève derrière le footer */
    .block-container {
        padding-bottom: 120px;
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
# 2. FONCTIONS UTILES
# =======================
def save_data_to_cloud(df_new):
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
    st.toast("Sauvegarde OK !", icon="☁️")

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
# 3. MAÎTRE-NAGEUR (REFONDU)
# =======================
def show_maitre_nageur():
    st.title("👨‍🏫 Appel Bassin")
    
    # Écran de succès après validation
    if st.session_state.get("appel_termine", False):
        st.success("✅ Enregistré avec succès !")
        if st.button("Nouveau Scan"):
            st.session_state.appel_termine = False
            for k in list(st.session_state.keys()):
                if k.startswith("cb_"): del st.session_state[k]
            st.rerun()
        return

    # Upload PDF
    up = st.file_uploader("Charger le PDF", type=["pdf"])
    if up:
        if 'current_file' not in st.session_state or st.session_state.current_file != up.name:
            st.session_state.current_file = up.name
            st.session_state.df_appel = parse_pdf_complete(up.read())

        df = st.session_state.df_appel
        if not df.empty:
            d_aff = df['Date'].iloc[0].strftime('%d/%m/%Y') if isinstance(df['Date'].iloc[0], (date, datetime)) else str(df['Date'].iloc[0])
            st.info(f"📅 {d_aff} | {df['Cours'].iloc[0]} ({df['Heure'].iloc[0]})")
            
            # --- BOUTONS GLOBAUX ---
            c1, c2 = st.columns(2)
            if c1.button("✅ TOUT PRÉSENT", use_container_width=True):
                for i in range(len(df)): st.session_state[f"cb_{i}"] = True
                st.rerun()
            if c2.button("❌ TOUT ABSENT", use_container_width=True):
                for i in range(len(df)): st.session_state[f"cb_{i}"] = False
                st.rerun()

            # --- OPTION RETARDATAIRES ---
            st.write("---")
            mode_retard = st.toggle("🕒 Mode Retardataires (Masquer les présents)")
            
            # --- LISTE DES ÉLÈVES ---
            st.write("### Liste des élèves")
            
            for idx, row in df.iterrows():
                k = f"cb_{idx}"
                # Initialisation de la checkbox si inexistante
                if k not in st.session_state: st.session_state[k] = False
                
                # Si mode retardataire activé ET que l'élève est présent, on saute l'affichage
                if mode_retard and st.session_state[k]:
                    continue
                
                # Layout Mobile : Checkbox à gauche (petite), Nom coloré à droite (grand)
                col_check, col_name = st.columns([1, 4])
                
                with col_check:
                    # Checkbox qui contrôle l'état
                    st.checkbox("P", key=k, label_visibility="collapsed")
                
                with col_name:
                    nom_complet = f"{row['Nom']} {row['Prenom']}"
                    # Affichage conditionnel Rouge/Vert selon la checkbox
                    if st.session_state[k]:
                        st.markdown(f'<div class="student-box-present">{nom_complet}</div>', unsafe_allow_html=True)
                    else:
                        st.markdown(f'<div class="student-box-absent">{nom_complet}</div>', unsafe_allow_html=True)
                
                # Mise à jour du DataFrame en temps réel
                df.at[idx, "Absent"] = not st.session_state[k]

            # --- AJOUT MANUEL ---
            st.write("---")
            with st.expander("➕ Ajouter un élève manuellement"):
                with st.form("add"):
                    nm = st.text_input("Nom de famille").upper()
                    pr = st.text_input("Prénom")
                    if st.form_submit_button("Ajouter"):
                        nr = df.iloc[0].copy()
                        nr["Nom"] = nm; nr["Prenom"] = pr if pr else "(Manuel)"; 
                        nr["Manuel"] = True; nr["Absent"] = False
                        # On ajoute au DF et on coche la case par défaut
                        st.session_state.df_appel = pd.concat([df, pd.DataFrame([nr])], ignore_index=True)
                        new_idx = len(st.session_state.df_appel) - 1
                        st.session_state[f"cb_{new_idx}"] = True
                        st.rerun()

            # --- FOOTER FIXE (RÉCAP + VALIDATION) ---
            nb_present = len(df[df["Absent"] == False])
            nb_total = len(df)
            
            # Injection HTML pour le footer fixe
            st.markdown(f"""
            <div class="fixed-footer">
                <div style="display: flex; justify-content: space-between; align-items: center; max-width: 800px; margin: 0 auto; color: white;">
                    <div style="font-size: 1.2rem; font-weight: bold;">
                        Présents : {nb_present} / {nb_total}
                    </div>
                    </div>
            </div>
            """, unsafe_allow_html=True)

            # Bouton Valider Streamlit standard (il sera juste au dessus du footer visuel ou dedans si CSS ajusté, 
            # ici on le garde en bas de flux normal mais visible grâce au padding-bottom)
            if st.button(f"💾 SAUVEGARDER L'APPEL ({nb_present}/{nb_total})", type="primary", use_container_width=True):
                save_data_to_cloud(df)
                st.session_state.appel_termine = True
                st.rerun()

# =======================
# 4. RÉCEPTION (AVEC FIX)
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
# 5. MANAGER
# =======================
def show_manager():
    st.title("📊 Manager")
    if st.sidebar.text_input("Mdp", type="password") != MANAGER_PASSWORD:
        st.warning("Accès refusé"); return
    
    # Simple vue des stats
    if not df_all.empty:
        tot = len(df_all)
        pres = len(df_all[df_all["Statut"]=="Présent"])
        st.metric("Taux de présence global", f"{pres/tot*100:.1f}%")
        st.dataframe(df_all)
    
    # Bouton Reset
    if st.checkbox("Activer suppression"):
        if st.button("🔥 VIDER LA BASE", type="primary"):
            ids = [r['id'] for r in table.all()]
            for i in range(0, len(ids), 10):
                table.batch_delete(ids[i:i+10])
            st.success("Base vidée.")
            st.rerun()

# =======================
# 6. ROUTER
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

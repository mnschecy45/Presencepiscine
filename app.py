import streamlit as st
import pandas as pd
import pdfplumber
import re
import io
import time
import altair as alt
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

# --- INITIALISATION SESSION STATE (Pour éviter AttributeError) ---
if "tpl_abs" not in st.session_state:
    st.session_state.tpl_abs = "Bonjour {nom},\n\nSauf erreur de notre part, nous avons relevé les absences suivantes :\n{details}\nMerci de nous confirmer votre situation.\n\nCordialement."
if "tpl_man" not in st.session_state:
    st.session_state.tpl_man = "Bonjour {nom},\n\nVous avez participé au cours de {cours} le {date} sans inscription préalable.\n\nMerci de régulariser votre passage à l'accueil.\n\nCordialement."

# --- STYLE CSS ---
st.markdown("""
    <style>
    /* PRÉSENT */
    .student-box-present {
        background-color: #1b5e20; color: white; padding: 15px; border-radius: 8px;
        font-weight: bold; font-size: 16px; margin-bottom: 5px; text-align: center; border: 1px solid #144a17;
    }
    /* ABSENT */
    .student-box-absent {
        background-color: #b71c1c; color: white; padding: 15px; border-radius: 8px;
        font-weight: bold; font-size: 16px; margin-bottom: 5px; text-align: center; border: 1px solid #7f0000;
    }
    /* Checkbox */
    .stCheckbox { display: flex; align-items: center; justify-content: center; height: 100%; padding-top: 10px; }
    /* Footer */
    .fixed-footer {
        position: fixed; bottom: 0; left: 0; width: 100%; background-color: #1e1e1e;
        padding: 10px 0; border-top: 3px solid #4CAF50; z-index: 9990;
        box-shadow: 0px -2px 10px rgba(0,0,0,0.5); color: white; font-family: sans-serif;
    }
    .footer-content { display: flex; justify-content: space-around; align-items: center; max-width: 800px; margin: 0 auto; }
    .footer-stat { text-align: center; }
    .footer-stat-val { font-size: 1.2rem; font-weight: bold; }
    .footer-stat-label { font-size: 0.7rem; opacity: 0.8; text-transform: uppercase; }
    .block-container { padding-bottom: 150px; }
    /* Metrics */
    [data-testid="stMetric"] { background-color: #f0f2f6; padding: 10px; border-radius: 5px; border: 1px solid #ddd; }
    </style>
""", unsafe_allow_html=True)

# =======================
# 2. CHARGEMENT DONNÉES (CORRECTIF KEYERROR)
# =======================
@st.cache_data(ttl=5)
def load_airtable_data():
    try:
        api = Api(API_TOKEN)
        table = api.table(BASE_ID, TABLE_NAME)
        records = table.all()
        
        # Structure vide par défaut
        if not records:
            return pd.DataFrame(columns=["Nom", "Prenom", "Date", "Heure", "Cours", "Statut", "Manuel", "Traite"]), table

        data = [r['fields'] for r in records]
        # On ajoute les IDs
        for i, r in enumerate(data):
            r['id'] = records[i]['id']
            
        df = pd.DataFrame(data)

        # --- FIX KEYERROR : On s'assure que toutes les colonnes existent ---
        required_cols = ["Nom", "Prenom", "Date", "Heure", "Cours", "Statut", "Manuel", "Traite"]
        for col in required_cols:
            if col not in df.columns:
                df[col] = None # Crée la colonne vide si manquante

        # Nettoyage
        df["Prenom"] = df["Prenom"].fillna("")
        df["Manuel"] = df["Manuel"].fillna(False)
        df["Traite"] = df["Traite"].fillna(False)
        df["Nom"] = df["Nom"].astype(str).str.upper()

        # Dates pour Manager
        if "Date" in df.columns:
            df["Date_dt"] = pd.to_datetime(df["Date"], errors='coerce')
            df = df.dropna(subset=["Date_dt"])
            df["Annee"] = df["Date_dt"].dt.year
            df["Mois"] = df["Date_dt"].dt.month
            jour_map = {0:"Lundi", 1:"Mardi", 2:"Mercredi", 3:"Jeudi", 4:"Vendredi", 5:"Samedi", 6:"Dimanche"}
            df["Jour"] = df["Date_dt"].dt.dayofweek.map(jour_map)

        return df, table
    except Exception as e:
        # En cas de crash total, renvoie vide safe
        return pd.DataFrame(columns=["Nom", "Date"]), None

df_all, airtable_table = load_airtable_data()

# =======================
# 3. FONCTIONS LOGIQUES
# =======================

def delete_previous_session_records(date_val, heure_val, cours_val):
    if df_all.empty or airtable_table is None: return
    d_str = date_val.strftime("%Y-%m-%d") if isinstance(date_val, (date, datetime)) else str(date_val)
    
    df_temp = df_all.copy()
    df_temp['Date_Str'] = df_temp['Date'].apply(lambda x: x if isinstance(x, str) else str(x))
    
    mask = (df_temp["Date_Str"] == d_str) & (df_temp["Heure"] == heure_val) & (df_temp["Cours"] == cours_val)
    to_delete = df_temp[mask]
    
    if not to_delete.empty:
        ids = to_delete['id'].tolist()
        for i in range(0, len(ids), 10):
            airtable_table.batch_delete(ids[i:i+10])
            
def save_data_to_cloud(df_new):
    if airtable_table is None: st.error("Erreur Airtable"); return

    first_row = df_new.iloc[0]
    d_val = first_row["Date"]; h_val = first_row["Heure"]; c_val = first_row["Cours"]
    
    with st.spinner("Enregistrement..."):
        delete_previous_session_records(d_val, h_val, c_val)
        
        prog = st.progress(0); total = len(df_new)
        for i, row in df_new.iterrows():
            try:
                statut = "Absent" if row["Absent"] else "Présent"
                d_str = row["Date"].strftime("%Y-%m-%d") if isinstance(row["Date"], (date, datetime)) else str(row["Date"])
                is_manuel = True if row.get("Manuel") else False
                
                rec = {
                    "Nom": str(row["Nom"]), "Statut": statut, "Date": d_str,
                    "Cours": str(row["Cours"]), "Heure": str(row["Heure"]), 
                    "Traite": False, "Manuel": is_manuel, "Prenom": str(row.get("Prenom", ""))
                }
                airtable_table.create(rec)
                prog.progress((i + 1) / total)
            except: pass
        prog.empty()
    
    st.session_state['latest_course_context'] = {'Date': d_val, 'Heure': h_val, 'Cours': c_val}
    st.toast("C'est enregistré !", icon="💾")
    load_airtable_data.clear()

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
                    if ts: h_deb = ts[0]; c_name = l[:l.index(ts[0])].strip(); break
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
# 4. MAÎTRE-NAGEUR
# =======================
def show_maitre_nageur():
    st.title("👨‍🏫 Appel Bassin")

    if st.session_state.get("appel_termine", False):
        st.success("✅ Appel mis à jour !")
        if st.button("Retour à l'accueil"):
            st.session_state.appel_termine = False
            for k in ['df_appel', 'current_file']:
                if k in st.session_state: del st.session_state[k]
            for k in list(st.session_state.keys()):
                if k.startswith("cb_"): del st.session_state[k]
            st.rerun()
        return

    # Bouton REPRENDRE LE DERNIER
    target_course = None
    if 'latest_course_context' in st.session_state:
        target_course = st.session_state['latest_course_context']
    elif not df_all.empty and "Date_dt" in df_all.columns:
        df_sorted = df_all.sort_values(["Date_dt", "Heure"], ascending=[False, False])
        df_last = df_sorted.drop_duplicates(subset=['Date', 'Heure', 'Cours']).head(1)
        if not df_last.empty:
            last_row = df_last.iloc[0]
            target_course = {'Date': last_row['Date'], 'Heure': last_row['Heure'], 'Cours': last_row['Cours']}

    if 'df_appel' not in st.session_state and target_course:
        d_aff = target_course['Date']
        if isinstance(d_aff, (date, datetime)): d_aff = d_aff.strftime("%d/%m/%Y")
        else: d_aff = str(d_aff)
        btn_label = f"🔄 REPRENDRE : {target_course['Cours']} ({d_aff} à {target_course['Heure']})"
        
        if st.button(btn_label, type="primary", use_container_width=True):
            d_target_str = target_course['Date']
            if isinstance(d_target_str, (date, datetime)): d_target_str = d_target_str.strftime("%Y-%m-%d")
            else: d_target_str = str(d_target_str)

            df_temp = df_all.copy()
            df_temp['Date_Str'] = df_temp['Date'].apply(lambda x: x.strftime("%Y-%m-%d") if isinstance(x, (date, datetime)) else str(x))
            mask = (df_temp["Date_Str"] == d_target_str) & (df_temp["Heure"] == target_course['Heure']) & (df_temp["Cours"] == target_course['Cours'])
            session_data = df_all[mask].copy()
            
            if session_data.empty: st.warning("Données introuvables.")
            else:
                reconstructed = []
                for _, r in session_data.iterrows():
                    reconstructed.append({
                        "Date": r['Date'], "Cours": r['Cours'], "Heure": r['Heure'],
                        "Nom": str(r['Nom']), "Prenom": str(r.get("Prenom", "")), 
                        "Absent": (r['Statut'] == "Absent"), "Manuel": True if r.get("Manuel") else False
                    })
                st.session_state.df_appel = pd.DataFrame(reconstructed)
                st.session_state["mode_retard"] = True 
                for idx, row in st.session_state.df_appel.iterrows(): st.session_state[f"cb_{idx}"] = not row["Absent"]
                st.rerun()

    if 'df_appel' not in st.session_state:
        st.write("---")
        st.markdown("#### 📂 Ou charger un nouveau PDF")
        up = st.file_uploader("Glisser le fichier planning ici", type=["pdf"])
        if up:
            st.session_state.current_file = up.name
            st.session_state.df_appel = parse_pdf_complete(up.read())
            st.session_state["mode_retard"] = False
            if 'latest_course_context' in st.session_state: del st.session_state['latest_course_context']
            for k in list(st.session_state.keys()):
                 if k.startswith("cb_"): del st.session_state[k]
            st.rerun()

    # Liste d'appel
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
                if mode_retard and st.session_state[k]: continue
                
                c_chk, c_nom = st.columns([1, 4])
                with c_chk: st.checkbox("P", key=k, label_visibility="collapsed")
                with c_nom:
                    full_n = f"{row['Nom']} {row['Prenom']}".strip()
                    if st.session_state[k]: st.markdown(f'<div class="student-box-present">{full_n}</div>', unsafe_allow_html=True)
                    else: st.markdown(f'<div class="student-box-absent">{full_n}</div>', unsafe_allow_html=True)
                df.at[idx, "Absent"] = not st.session_state[k]

            st.write("---")
            with st.expander("➕ Ajout Manuel (Non-Inscrit)"):
                with st.form("add"):
                    nm = st.text_input("Nom").upper()
                    if st.form_submit_button("Ajouter"):
                        nr = df.iloc[0].copy()
                        nr["Nom"] = nm; nr["Prenom"] = "(Manuel)"; nr["Manuel"] = True; nr["Absent"] = False
                        st.session_state.df_appel = pd.concat([df, pd.DataFrame([nr])], ignore_index=True)
                        new_idx = len(st.session_state.df_appel) - 1
                        st.session_state[f"cb_{new_idx}"] = True
                        st.rerun()

            nb_p = len(df[df["Absent"]==False]); nb_a = len(df[df["Absent"]==True]); nb_t = len(df)
            st.markdown(f"""<div class="fixed-footer"><div class="footer-content">
                <div class="footer-stat"><div class="footer-stat-val">{nb_t}</div><div class="footer-stat-label">TOTAL</div></div>
                <div class="footer-stat" style="color:#4CAF50;"><div class="footer-stat-val">{nb_p}</div><div class="footer-stat-label">PRÉSENTS</div></div>
                <div class="footer-stat" style="color:#f44336;"><div class="footer-stat-val">{nb_a}</div><div class="footer-stat-label">ABSENTS</div></div>
            </div></div>""", unsafe_allow_html=True)

            if st.button("💾 SAUVEGARDER L'APPEL", type="primary", use_container_width=True):
                save_data_to_cloud(df)
                st.session_state.appel_termine = True
                st.rerun()

# =======================
# 5. PAGE RÉCEPTION
# =======================
def show_reception():
    st.title("💁 Réception")
    if df_all.empty: st.info("Chargement..."); return
    
    t1, t2 = st.tabs(["⚡ ABSENCES", "⚠️ NON INSCRITS"])
    
    with t1:
        mask = (df_all["Statut"]=="Absent") & (df_all["Traite"]!=True)
        if "Manuel" in df_all.columns: mask = mask & (df_all["Manuel"] == False)
        
        todo = df_all[mask]
        if todo.empty: st.success("Tout est traité.")
        else:
            cli = st.selectbox("Sélectionner un absent", todo["Nom"].unique())
            if cli:
                sub = todo[todo["Nom"]==cli].sort_values("Date_dt", ascending=False)
                details = ""
                for _, r in sub.iterrows():
                    d_fmt = r["Date_dt"].strftime("%d/%m") if pd.notnull(r["Date_dt"]) else str(r["Date"])
                    details += f"- {r['Cours']} le {d_fmt}\n"
                
                final_msg = st.session_state.tpl_abs.replace("{nom}", cli).replace("{details}", details)
                st.info(f"{len(sub)} absences.")
                st.text_area("Message", value=final_msg, height=150)
                if st.button("✅ Marquer Traité", key="t_abs"):
                    for pid in sub['id']: airtable_table.update(pid, {"Traite": True})
                    st.success("Fait !"); time.sleep(1); load_airtable_data.clear(); st.rerun()

    with t2:
        mask_m = (df_all["Traite"]!=True)
        if "Manuel" in df_all.columns: mask_m = mask_m & (df_all["Manuel"] == True)
        else: mask_m = mask_m & (df_all["Prenom"] == "(Manuel)")
        mans = df_all[mask_m]
        
        if mans.empty: st.info("RAS")
        else:
            cli_m = st.selectbox("Non Inscrit", mans["Nom"].unique())
            if cli_m:
                sub_m = mans[mans["Nom"]==cli_m].sort_values("Date_dt", ascending=False)
                last = sub_m.iloc[0]
                d_fmt = last["Date_dt"].strftime("%d/%m") if pd.notnull(last["Date_dt"]) else str(last["Date"])
                msg = st.session_state.tpl_man.replace("{nom}", cli_m).replace("{date}", d_fmt).replace("{cours}", str(last["Cours"]))
                st.warning("Passage non inscrit.")
                st.text_area("Message", value=msg, height=150)
                if st.button("✅ Régularisé", key="t_man"):
                    for pid in sub_m['id']: airtable_table.update(pid, {"Traite": True})
                    st.success("Fait !"); time.sleep(1); load_airtable_data.clear(); st.rerun()

# =======================
# 6. PAGE MANAGER (RESTAURÉE COMPLETE)
# =======================
def show_manager():
    st.title("📊 Manager")
    if st.sidebar.text_input("Mot de passe", type="password") != MANAGER_PASSWORD: return
    
    tab1, tab2, tab3, tab4 = st.tabs(["📈 DASHBOARD", "🔎 ANALYSE COMPARÉE", "⚙️ CONFIG", "🛠️ MAINT."])

    # 1. DASHBOARD GLOBAL
    with tab1:
        st.subheader("Vue d'ensemble")
        if df_all.empty:
            st.info("Aucune donnée")
        else:
            # Filtres
            c1, c2 = st.columns(2)
            yrs = sorted(df_all["Annee"].dropna().unique(), reverse=True)
            sel_yr = c1.selectbox("Année", yrs) if len(yrs)>0 else None
            df_yr = df_all[df_all["Annee"]==sel_yr] if sel_yr else df_all
            
            mois_dispo = sorted(df_yr["Mois"].dropna().unique())
            sel_mois = c2.selectbox("Mois", ["TOUS"] + list(mois_dispo))
            df_filt = df_yr[df_yr["Mois"]==sel_mois] if sel_mois != "TOUS" else df_yr
            
            # Stats
            tot = len(df_filt)
            pres = len(df_filt[df_filt["Statut"]=="Présent"])
            absent = len(df_filt[df_filt["Statut"]=="Absent"])
            taux = (pres/tot*100) if tot>0 else 0
            
            k1, k2, k3 = st.columns(3)
            k1.metric("Inscrits", tot)
            k2.metric("Présents", pres, f"{taux:.1f}%")
            k3.metric("Absents", absent, delta_color="inverse")
            
            st.divider()
            g1, g2 = st.columns(2)
            with g1:
                st.write("**Fréquentation par Jour**")
                if not df_filt.empty and "Jour" in df_filt.columns:
                    ch = alt.Chart(df_filt[df_filt["Statut"]=="Présent"]).mark_bar().encode(
                        x=alt.X('Jour', sort=["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]),
                        y='count()',
                        color=alt.value("#4CAF50")
                    )
                    st.altair_chart(ch, use_container_width=True)
            with g2:
                st.write("**Top Cours (Présence)**")
                if not df_filt.empty:
                    chart_c = alt.Chart(df_filt[df_filt["Statut"]=="Présent"]).mark_bar().encode(
                        y=alt.Y('Cours', sort='-x'),
                        x='count()',
                        color=alt.value("#2196F3")
                    )
                    st.altair_chart(chart_c, use_container_width=True)
            
            st.write("**Top Absents**")
            if not df_filt.empty:
                top = df_filt[df_filt["Statut"]=="Absent"]["Nom"].value_counts().head(5)
                st.dataframe(top, use_container_width=True)

    # 2. ANALYSE DETAILLEE
    with tab2:
        st.subheader("Comparateur & Évolution")
        mode = st.radio("Mode", ["Évolution d'un cours", "Comparaison Périodes"], horizontal=True)
        
        if mode == "Évolution d'un cours":
            if not df_all.empty:
                cours_list = sorted(df_all["Cours"].dropna().unique())
                c_choix = st.selectbox("Choisir un cours", cours_list)
                if c_choix:
                    data_c = df_all[(df_all["Cours"]==c_choix) & (df_all["Statut"]=="Présent")]
                    if not data_c.empty:
                        chart_line = alt.Chart(data_c).mark_line(point=True).encode(
                            x='Date_dt:T', y='count()', tooltip=['Date_dt', 'count()']
                        ).properties(title=f"Présence : {c_choix}")
                        st.altair_chart(chart_line, use_container_width=True)
                    else: st.warning("Pas de données.")
        else:
            if not df_all.empty:
                c_a, c_b = st.columns(2)
                m_a = c_a.selectbox("Mois A", sorted(df_all["Mois"].unique()), key="ma")
                m_b = c_b.selectbox("Mois B", sorted(df_all["Mois"].unique()), key="mb")
                d_a = df_all[df_all["Mois"]==m_a]
                d_b = df_all[df_all["Mois"]==m_b]
                c_a.metric(f"Mois {m_a}", len(d_a))
                c_b.metric(f"Mois {m_b}", len(d_b), delta=len(d_b)-len(d_a))

    # 3. CONFIG
    with tab3:
        st.subheader("Messages Réception")
        c1, c2 = st.columns(2)
        with c1:
            st.write("Modèle Absences ({nom}, {details})")
            new_abs = st.text_area("Txt Abs", st.session_state.tpl_abs, height=150)
            if st.button("Sauvegarder Abs"): st.session_state.tpl_abs = new_abs; st.success("OK")
        with c2:
            st.write("Modèle Non-Inscrits ({nom}, {cours}, {date})")
            new_man = st.text_area("Txt Man", st.session_state.tpl_man, height=150)
            if st.button("Sauvegarder Man"): st.session_state.tpl_man = new_man; st.success("OK")

    # 4. MAINTENANCE
    with tab4:
        st.dataframe(df_all)
        if st.button("🔥 VIDER BASE"):
            ids = [r['id'] for r in airtable_table.all()]
            for i in range(0, len(ids), 10): airtable_table.batch_delete(ids[i:i+10])
            load_airtable_data.clear(); st.rerun()

# =======================
# 7. ROUTER
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
import streamlit as st
import pandas as pd
import pdfplumber
import re
import io
import altair as alt
from datetime import datetime, date
from pyairtable import Api

# =======================
# 0. VOS CLES AIRTABLE (A REMPLIR)
# =======================
API_TOKEN = "pat85co2rWjG48EDz.e6e628e1b5da543271388625e0006a0186a2e424ff7a3ae6e146508794f8edbd" # Ton token
BASE_ID = "app390ytx6oa2rbge"    # Ton ID de base
TABLE_NAME = "Presences"             # Nom de l'onglet

# =======================
# 1. CONFIGURATION & CHARGEMENT
# =======================
st.set_page_config(page_title="Piscine Pro", layout="wide", page_icon="🏊‍♂️")

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
# 3. MAÎTRE-NAGEUR
# =======================
def show_maitre_nageur():
    st.title("👨‍🏫 Appel Bassin")
    if st.session_state.get("appel_termine", False):
        st.success("✅ Enregistré !")
        if st.button("Nouveau"):
            st.session_state.appel_termine = False
            for k in list(st.session_state.keys()):
                if k.startswith("cb_"): del st.session_state[k]
            st.rerun()
        return

    up = st.file_uploader("PDF", type=["pdf"])
    if up:
        if 'current_file' not in st.session_state or st.session_state.current_file != up.name:
            st.session_state.current_file = up.name
            st.session_state.df_appel = parse_pdf_complete(up.read())

        df = st.session_state.df_appel
        if not df.empty:
            d_aff = df['Date'].iloc[0].strftime('%d/%m/%Y') if isinstance(df['Date'].iloc[0], (date, datetime)) else str(df['Date'].iloc[0])
            st.info(f"📅 {d_aff} | {df['Cours'].iloc[0]} ({df['Heure'].iloc[0]})")
            
            c1, c2 = st.columns(2)
            if c1.button("✅ TOUT PRÉSENT"):
                for i in range(len(df)): st.session_state[f"cb_{i}"] = True
                st.rerun()
            if c2.button("❌ TOUT ABSENT"):
                for i in range(len(df)): st.session_state[f"cb_{i}"] = False
                st.rerun()

            st.write("---")
            for idx, row in df.iterrows():
                k = f"cb_{idx}"
                if k not in st.session_state: st.session_state[k] = False
                bg = "#dcfce7" if st.session_state[k] else "#fee2e2"
                c_n, c_c = st.columns([4, 1])
                c_n.markdown(f"<div style='padding:8px; background:{bg}; border-radius:5px;'><b>{row['Nom']} {row['Prenom']}</b></div>", unsafe_allow_html=True)
                st.checkbox("P", key=k, label_visibility="collapsed")
                df.at[idx, "Absent"] = not st.session_state[k]

            st.write("---")
            with st.expander("➕ Ajout Manuel"):
                with st.form("add"):
                    nm = st.text_input("Nom").upper()
                    if st.form_submit_button("Ajouter"):
                        nr = df.iloc[0].copy()
                        nr["Nom"] = nm; nr["Prenom"] = "(Manuel)"; nr["Manuel"] = True; nr["Absent"] = False
                        st.session_state.df_appel = pd.concat([df, pd.DataFrame([nr])], ignore_index=True)
                        st.rerun()

            if st.button("💾 SAUVEGARDER", type="primary"):
                save_data_to_cloud(df)
                st.session_state.appel_termine = True
                st.rerun()

# =======================
# 4. RÉCEPTION
# =======================
def show_reception():
    st.title("💁 Réception")
    if df_all.empty: 
        st.warning("Base vide. Importez des données via le Manager.")
        return

    df_w = df_all.copy()
    if "Date_dt" not in df_w.columns and "Date" in df_w.columns:
         df_w["Date_dt"] = pd.to_datetime(df_w["Date"], errors='coerce')
    if "Traite" not in df_w.columns: df_w["Traite"] = False

    t1, t2 = st.tabs(["⚡ À TRAITER", "✅ HISTORIQUE"])

    with t1:
        todo = df_w[(df_w["Statut"] == "Absent") & (df_w["Traite"] != True)]
        if todo.empty:
            st.success("Rien à traiter.")
        else:
            st.write(f"**{len(todo)} absences**")
            cli = st.selectbox("Client", todo["Nom"].unique())
            if cli:
                tot_abs = len(df_w[(df_w["Nom"] == cli) & (df_w["Statut"] == "Absent")])
                s1 = st.session_state.get("p1_val", 1); s2 = st.session_state.get("p2_val", 3); s3 = st.session_state.get("p3_val", 5)
                l1 = st.session_state.get("p1_label", "Mail"); l2 = st.session_state.get("p2_label", "Tel"); l3 = st.session_state.get("p3_label", "RDV")
                
                niv = 1
                lbl = l1
                if tot_abs >= s3: niv=3; lbl=l3
                elif tot_abs >= s2: niv=2; lbl=l2
                
                color = "🔴" if niv==3 else "🟠" if niv==2 else "🟡"
                st.markdown(f"### {color} NIVEAU {niv} - {lbl} ({tot_abs} abs)")

                sub = todo[todo["Nom"] == cli].sort_values("Date_dt", ascending=False)
                ids, txts = [], []
                for _, r in sub.iterrows():
                    ids.append(r['id'])
                    d = r["Date_dt"].strftime("%d/%m") if pd.notnull(r["Date_dt"]) else "?"
                    c = r.get("Cours", "Séance")
                    txts.append(f"- {c} le {d}")
                
                det = "\n".join(txts)
                msg_val = ""
                btn_txt = f"✅ Action {lbl} Faite"
                
                # TEMPLATES
                tpl_def_p1 = "Bonjour {prenom},\n\nSauf erreur de notre part, nous avons relevé les absences suivantes :\n{details}\n\nMerci de confirmer votre présence."
                tpl_def_p3 = "Bonjour {prenom},\n\nSuite à de nombreuses absences ({details}), merci de passer à l'accueil."
                tpl_p1 = st.session_state.get("msg_tpl", tpl_def_p1)
                tpl_p3 = st.session_state.get("msg_p3_tpl", tpl_def_p3)

                if niv == 2:
                    st.write("**Action : APPEL**")
                    st.info("Script : Bonjour, tout va bien ?")
                elif niv == 3:
                    st.write("**Action : CONVOCATION**")
                    msg_val = tpl_p3.replace("{prenom}", cli).replace("{details}", det)
                    st.text_area("Copier :", msg_val, height=150)
                else:
                    st.write("**Action : MAIL**")
                    msg_val = tpl_p1.replace("{prenom}", cli).replace("{details}", det)
                    st.text_area("Copier :", msg_val, height=150)

                if st.button(btn_txt, type="primary"):
                    now = datetime.now().strftime("%Y-%m-%d %H:%M")
                    for pid in ids:
                        try: table.update(pid, {"Traite": True, "Date_Traitement": now})
                        except: pass
                    st.success("Archivé !")
                    st.rerun()

    with t2:
        done = df_w[(df_w["Statut"] == "Absent") & (df_w["Traite"] == True)]
        if not done.empty:
            cols = ["Nom", "Date", "Cours"]
            if "Date_Traitement" in done.columns:
                cols.append("Date_Traitement")
                done = done.sort_values("Date_Traitement", ascending=False)
            st.dataframe(done[cols], use_container_width=True)
        else:
            st.info("Vide")

# =======================
# 5. MANAGER (CORRIGÉ : TABS VISIBLES MEME SI VIDE)
# =======================
def show_manager():
    # CSS FORCE NOIR
    st.markdown("""
        <style>
        [data-testid="stMetric"] {
            background-color: #f8f9fa !important;
            border: 1px solid #dee2e6 !important;
            padding: 15px !important;
            border-radius: 10px !important;
            color: black !important;
        }
        [data-testid="stMetric"] label { color: #333 !important; }
        [data-testid="stMetric"] div[data-testid="stMetricValue"] { color: #000 !important; }
        [data-testid="stMetric"] p { color: #000 !important; }
        </style>
    """, unsafe_allow_html=True)
    st.title("📊 Manager")

    if st.sidebar.text_input("Mdp", type="password") != MANAGER_PASSWORD:
        st.warning("Accès refusé"); return
    
    # --- PREPA DONNEES (Sécurisée : Pas de "stop" si vide) ---
    df_ana = pd.DataFrame()
    if not df_all.empty:
        df_ana = df_all.copy()
        if "Date_dt" not in df_ana.columns and "Date" in df_ana.columns:
             df_ana["Date_dt"] = pd.to_datetime(df_ana["Date"], errors='coerce')
        df_ana = df_ana.dropna(subset=["Date_dt"])

        def clean_h(v):
            if pd.isna(v): return "?"
            s = str(v)
            if len(s) > 8 and (" " in s or "T" in s):
                try: return s.replace("T", " ").split(" ")[-1][:5]
                except: return s
            return s

        if "Heure" in df_ana.columns: df_ana["Heure"] = df_ana["Heure"].apply(clean_h).astype(str)
        else: df_ana["Heure"] = "?"

        if "Cours" not in df_ana.columns: df_ana["Cours"] = "Inconnu"
        df_ana["Cours"] = df_ana["Cours"].fillna("Inconnu").astype(str)

        jours = {0:"Lundi", 1:"Mardi", 2:"Mercredi", 3:"Jeudi", 4:"Vendredi", 5:"Samedi", 6:"Dimanche"}
        df_ana["Jour_Num"] = df_ana["Date_dt"].dt.dayofweek
        df_ana["Jour"] = df_ana["Jour_Num"].map(jours).fillna("?").astype(str)
        
        df_ana["Annee"] = df_ana["Date_dt"].dt.year
        df_ana["Mois"] = df_ana["Date_dt"].dt.month
        df_ana["Semaine"] = df_ana["Date_dt"].dt.isocalendar().week
        df_ana["Cours_Complet"] = df_ana["Cours"] + " (" + df_ana["Jour"] + " " + df_ana["Heure"] + ")"

    # --- TABS ---
    t_dash, t_comp, t_conf, t_maint = st.tabs(["📊 DASHBOARD", "🚀 ANALYSE", "⚙️ CONFIG", "🛠️ MAINTENANCE"])

    # ----------------------------------------------------
    # TAB 1 : DASHBOARD
    # ----------------------------------------------------
    with t_dash:
        if df_ana.empty:
            st.info("Base vide. Allez dans l'onglet 'MAINTENANCE' pour importer vos données.")
        else:
            st.sidebar.header("📅 Filtres")
            yrs = sorted(df_ana["Annee"].unique(), reverse=True)
            yr = st.sidebar.selectbox("Année", yrs)
            df_yr = df_ana[df_ana["Annee"] == yr]

            # DICTIONNAIRE MOIS
            mois_map = {1: "Janvier", 2: "Février", 3: "Mars", 4: "Avril", 5: "Mai", 6: "Juin",
                7: "Juillet", 8: "Août", 9: "Septembre", 10: "Octobre", 11: "Novembre", 12: "Décembre"}

            vue = st.sidebar.radio("Vue", ["Mois", "Semaine"])
            if vue == "Mois":
                mths_nums = sorted(df_yr["Mois"].unique())
                mths_names = ["TOUS"] + [mois_map.get(m, str(m)) for m in mths_nums]
                ms = st.sidebar.selectbox("Mois", mths_names)
                if ms == "TOUS": df_filt = df_yr.copy()
                else:
                    choix_num = [k for k, v in mois_map.items() if v == ms][0]
                    df_filt = df_yr[df_yr["Mois"] == choix_num].copy()
            else:
                sems = sorted(df_yr["Semaine"].unique())
                sl = [f"Semaine {s}" for s in sems]
                ss = st.sidebar.selectbox("Semaine", sl)
                df_filt = df_yr[df_yr["Semaine"] == int(ss.split()[1])].copy()

            tot = len(df_filt)
            pres = len(df_filt[df_filt["Statut"]=="Présent"])
            absent = len(df_filt[df_filt["Statut"]=="Absent"])
            taux = (pres/tot*100) if tot>0 else 0
            c1, c2, c3 = st.columns(3)
            c1.metric("Inscrits", tot)
            c2.metric("Présents", pres, f"{taux:.1f}%")
            c3.metric("Absents", absent, delta_color="inverse")
            
            st.divider()
            st.subheader("📈 Fréquentation")
            if not df_filt.empty:
                da = df_filt[df_filt["Statut"]=="Présent"].groupby("Date_dt").size()
                da.index = da.index.strftime("%d/%m")
                st.area_chart(da, color="#3b82f6")
            
            st.divider()
            g1, g2 = st.columns(2)
            with g1:
                st.subheader("🔥 Top Cours")
                if not df_filt.empty:
                    tc = df_filt[df_filt["Statut"]=="Présent"]["Cours_Complet"].value_counts().head(10)
                    st.bar_chart(tc)
            with g2:
                st.subheader("📅 Par Jour")
                if not df_filt.empty:
                    sem_counts = df_filt[df_filt["Statut"]=="Présent"].groupby("Jour").size()
                    ordre_jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
                    sem_df = pd.DataFrame(sem_counts).reindex(ordre_jours, fill_value=0).reset_index()
                    sem_df.columns = ["Jour", "Nombre"]
                    chart_j = alt.Chart(sem_df).mark_bar(color="#76b900").encode(
                        x=alt.X('Jour', sort=ordre_jours, title=None),
                        y=alt.Y('Nombre', title=None)
                    )
                    st.altair_chart(chart_j, use_container_width=True)

            st.divider()
            st.subheader("📋 Détails Créneaux")
            if not df_filt.empty:
                synt = df_filt.groupby(["Jour_Num", "Jour", "Heure", "Cours"]).agg(
                    Inscrits=('Nom', 'count'),
                    Presents=('Statut', lambda x: (x=='Présent').sum())
                ).reset_index()
                synt["Taux %"] = (synt["Presents"]/synt["Inscrits"]*100).round(1)
                synt.sort_values(["Jour_Num", "Heure"], inplace=True)
                st.dataframe(synt[["Jour", "Heure", "Cours", "Inscrits", "Presents", "Taux %"]], use_container_width=True, hide_index=True)
                
            st.divider()
            k1, k2 = st.columns(2)
            with k1:
                st.subheader("🚨 Top Absents")
                if not df_filt.empty:
                    ta = df_filt[df_filt["Statut"]=="Absent"]["Nom"].value_counts().head(10).reset_index(name="Abs")
                    st.dataframe(ta, use_container_width=True, hide_index=True)
            with k2:
                st.subheader("🏆 Top Assidus")
                if not df_filt.empty:
                    tp = df_filt[df_filt["Statut"]=="Présent"]["Nom"].value_counts().head(10).reset_index(name="Pres")
                    st.dataframe(tp, use_container_width=True, hide_index=True)

    # ----------------------------------------------------
    # TAB 2 : ANALYSE
    # ----------------------------------------------------
    with t_comp:
        if df_ana.empty: st.info("Base vide. Allez dans Maintenance."); 
        else:
            st.info("📊 Suivez la tendance.")
            ct1, ct2 = st.tabs(["📉 Évolution Cours", "🆚 Comparateur Périodes"])
            
            with ct1:
                liste_cours = sorted([str(c) for c in df_ana["Cours_Complet"].unique() if str(c) != "nan" and str(c) != "Inconnu"])
                c_choix = st.selectbox("Choisir un cours :", liste_cours)
                if c_choix:
                    sub_c = df_ana[df_ana["Cours_Complet"] == c_choix].groupby("Date_dt").size()
                    st.line_chart(sub_c)
            
            with ct2:
                if vue == "Semaine":
                    l_s = sorted(df_ana["Semaine"].unique())
                    sa = st.selectbox("Sem A", l_s, index=0)
                    sb = st.selectbox("Sem B", l_s, index=len(l_s)-1 if len(l_s)>0 else 0)
                    da = df_ana[df_ana["Semaine"]==sa]; db = df_ana[df_ana["Semaine"]==sb]
                    la = f"Sem {sa}"; lb = f"Sem {sb}"
                else:
                    l_m_nums = sorted(df_ana["Mois"].unique())
                    l_m_names = [mois_map.get(m, str(m)) for m in l_m_nums]
                    ma_txt = st.selectbox("Mois A", l_m_names, index=0)
                    mb_txt = st.selectbox("Mois B", l_m_names, index=len(l_m_names)-1 if len(l_m_names)>0 else 0)
                    ma_num = [k for k, v in mois_map.items() if v == ma_txt][0]
                    mb_num = [k for k, v in mois_map.items() if v == mb_txt][0]
                    da = df_ana[df_ana["Mois"]==ma_num]; db = df_ana[df_ana["Mois"]==mb_num]
                    la = f"{ma_txt}"; lb = f"{mb_txt}"
                
                pa = len(da[da["Statut"]=="Présent"]); pb = len(db[db["Statut"]=="Présent"])
                c1, c2 = st.columns(2)
                c1.metric(f"Présents {la}", pa)
                c2.metric(f"Présents {lb}", pb, delta=pb-pa)

    # ----------------------------------------------------
    # TAB 3 : CONFIG
    # ----------------------------------------------------
    with t_conf:
        st.header("⚙️ Config")
        c_s, c_m = st.columns(2)
        with c_s:
            st.subheader("Paliers")
            st.number_input("P1", key="p1_val", value=1)
            st.text_input("Label P1", key="p1_label", value="Mail")
            st.number_input("P2", key="p2_val", value=3)
            st.text_input("Label P2", key="p2_label", value="Tel")
            st.number_input("P3", key="p3_val", value=5)
            st.text_input("Label P3", key="p3_label", value="RDV")
        
        with c_m:
            st.subheader("Messages")
            # RESTORE BUTTON
            if st.button("🔄 Restaurer les modèles par défaut"):
                st.session_state.msg_tpl = "Bonjour {prenom},\n\nSauf erreur de notre part, nous avons relevé les absences suivantes :\n{details}\n\nMerci de confirmer votre présence."
                st.session_state.msg_p3_tpl = "Bonjour {prenom},\n\nSuite à de nombreuses absences ({details}), merci de passer à l'accueil."
                st.rerun()

            st.text_area("Msg P1", key="msg_tpl", height=150)
            st.text_area("Msg P3", key="msg_p3_tpl", height=150)
        
        if st.button("Sauvegarder Config"): st.success("OK")

    # ----------------------------------------------------
    # TAB 4 : MAINTENANCE
    # ----------------------------------------------------
    with t_maint:
        st.header("🛠️ Maintenance")
        st.warning("Attention : Actions irréversibles.")
        
        col_import, col_reset = st.columns(2)
        
        with col_import:
            st.subheader("📥 Importer CSV")
            st.info("Format: nom, prenom, heure_debut, absent...")
            up_csv = st.file_uploader("Fichier CSV", type=["csv"])
            
            if up_csv:
                if st.button("Lancer Import"):
                    try:
                        df_csv = pd.read_csv(up_csv)
                        df_csv.columns = [c.lower() for c in df_csv.columns]
                        prog = st.progress(0)
                        tot = len(df_csv)
                        for i, row in df_csv.iterrows():
                            # 1. Nom complet
                            nom_brut = str(row.get('nom', '')).upper()
                            prenom_brut = str(row.get('prenom', ''))
                            nom_complet = f"{nom_brut} {prenom_brut}".strip() or "Inconnu"
                            
                            # 2. Champs
                            date_val = str(row.get('date', str(date.today())))
                            heure_val = str(row.get('heure_debut', '00h00'))
                            cours_val = str(row.get('cours', 'Inconnu'))
                            is_absent = str(row.get('absent', '')).lower() == 'true'
                            statut_val = "Absent" if is_absent else "Présent"

                            rec = {
                                "Nom": nom_complet,
                                "Statut": statut_val,
                                "Date": date_val,
                                "Cours": cours_val,
                                "Heure": heure_val,
                                "Traite": True 
                            }
                            table.create(rec)
                            prog.progress((i + 1) / tot)
                        prog.empty()
                        st.success("✅ Import réussi !")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erreur import : {e}")

        with col_reset:
            st.subheader("🗑️ Reset Total")
            if st.checkbox("Confirmer suppression totale"):
                if st.button("🔥 TOUT VIDER", type="primary"):
                    try:
                        ids = [r['id'] for r in table.all()]
                        if not ids: st.info("Déjà vide.")
                        else:
                            prog = st.progress(0)
                            bs = 10
                            for i in range(0, len(ids), bs):
                                batch = ids[i:i + bs]
                                table.batch_delete(batch)
                                prog.progress(min((i + bs) / len(ids), 1.0))
                            prog.empty()
                            st.success("Base vidée.")
                            st.rerun()
                    except Exception as e: st.error(f"Erreur : {e}")

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
    if st.sidebar.button("🏠"): go("HUB")
    show_maitre_nageur()
elif st.session_state.page == "REC":
    if st.sidebar.button("🏠"): go("HUB")
    show_reception()
elif st.session_state.page == "MGR":
    if st.sidebar.button("🏠"): go("HUB")
    show_manager()

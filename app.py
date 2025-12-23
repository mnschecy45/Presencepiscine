import streamlit as st
import pandas as pd
import pdfplumber
import re
import io
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
    st.error(f"Erreur de connexion Airtable : {e}")
    df_all = pd.DataFrame()

# =======================
# 2. FONCTIONS UTILES
# =======================
def save_data_to_cloud(df_new):
    progress_bar = st.progress(0)
    total = len(df_new)
    for i, row in df_new.iterrows():
        try:
            statut_final = "Absent" if row["Absent"] else "Présent"
            date_str = row["Date"].strftime("%Y-%m-%d") if isinstance(row["Date"], (date, datetime)) else str(row["Date"])
            record = {
                "Nom": row["Nom"],
                "Statut": statut_final, 
                "Date": date_str,
                "Cours": row["Cours"],
                "Heure": row["Heure"],
                "Traite": False
            }
            table.create(record)
            progress_bar.progress((i + 1) / total)
        except Exception as e:
            st.error(f"Erreur : {e}")
    progress_bar.empty()
    st.toast("Sauvegarde terminée !", icon="☁️")

def parse_pdf_complete(file_bytes):
    rows = []
    ignore = ["TCPDF", "www.", "places", "réservées", "disponibles", "ouvertes", "le ", " à ", "Page ", "Généré"]
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
                start_index = 0
                for i, l in enumerate(lines):
                    if "N° réservation" in l: start_index = i + 1; break
                for l in lines[start_index:]:
                    if not l.strip() or any(x in l for x in ignore): continue
                    l_clean = re.sub(r'\d+', '', l).strip()
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
# 3. MAÎTRE-NAGEUR
# =======================
def show_maitre_nageur():
    st.title("👨‍🏫 Appel Bassin")
    if st.session_state.get("appel_termine", False):
        st.success("✅ Appel enregistré !")
        if st.button("Nouvel appel"):
            st.session_state.appel_termine = False
            for key in list(st.session_state.keys()):
                if key.startswith("cb_"): del st.session_state[key]
            st.rerun()
        return

    up = st.file_uploader("Charger PDF", type=["pdf"])
    if up:
        if 'current_file' not in st.session_state or st.session_state.current_file != up.name:
            st.session_state.current_file = up.name
            st.session_state.df_appel = parse_pdf_complete(up.read())

        df = st.session_state.df_appel
        if not df.empty:
            d_obj = df['Date'].iloc[0]
            d_aff = d_obj.strftime('%d/%m/%Y') if isinstance(d_obj, (date, datetime)) else str(d_obj)
            st.info(f"📅 **{d_aff}** | {df['Cours'].iloc[0]} ({df['Heure'].iloc[0]})")

            c1, c2 = st.columns(2)
            if c1.button("✅ TOUT PRÉSENT"):
                for i in range(len(df)): st.session_state[f"cb_{i}"] = True
                st.rerun()
            if c2.button("❌ TOUT ABSENT"):
                for i in range(len(df)): st.session_state[f"cb_{i}"] = False
                st.rerun()
            
            st.write("---")
            for idx, row in df.iterrows():
                key = f"cb_{idx}"
                if key not in st.session_state: st.session_state[key] = False
                bg = "#dcfce7" if st.session_state[key] else "#fee2e2"
                col_n, col_c = st.columns([4, 1])
                col_n.markdown(f"<div style='padding:10px; background:{bg}; border-radius:5px;'><b>{row['Nom']} {row['Prenom']}</b></div>", unsafe_allow_html=True)
                st.checkbox("Présent", key=key, label_visibility="collapsed")
                df.at[idx, "Absent"] = not st.session_state[key]

            st.write("---")
            with st.expander("➕ Ajouter un client manuellement"):
                with st.form("add_m"):
                    nom_m = st.text_input("Nom").upper()
                    if st.form_submit_button("Ajouter"):
                        nr = df.iloc[0].copy()
                        nr["Nom"] = nom_m
                        nr["Prenom"] = "(Manuel)"
                        nr["Manuel"] = True
                        nr["Absent"] = False
                        st.session_state.df_appel = pd.concat([df, pd.DataFrame([nr])], ignore_index=True)
                        st.rerun()

            st.metric("Clients dans l'eau", len(df[df["Absent"]==False]))
            if st.button("💾 ENREGISTRER", type="primary"):
                save_data_to_cloud(df)
                st.session_state.appel_termine = True
                st.rerun()

# =======================
# 4. RÉCEPTION
# =======================
def show_reception():
    st.title("💁 Réception")
    if df_all.empty: return

    df_work = df_all.copy()
    if "Date_dt" not in df_work.columns and "Date" in df_work.columns:
         df_work["Date_dt"] = pd.to_datetime(df_work["Date"], errors='coerce')
    if "Traite" not in df_work.columns: df_work["Traite"] = False

    tab1, tab2 = st.tabs(["⚡ À TRAITER", "✅ HISTORIQUE"])

    with tab1:
        df_todo = df_work[(df_work["Statut"] == "Absent") & (df_work["Traite"] != True)]
        if df_todo.empty:
            st.success("Tout est à jour !")
        else:
            st.write(f"**{len(df_todo)} absences** en attente.")
            client = st.selectbox("Client", df_todo["Nom"].unique())
            if client:
                all_abs = df_work[(df_work["Nom"] == client) & (df_work["Statut"] == "Absent")]
                nb = len(all_abs)
                
                s1 = st.session_state.get("p1_val", 1)
                s2 = st.session_state.get("p2_val", 3)
                s3 = st.session_state.get("p3_val", 5)
                
                niv = 1
                if nb >= s3: niv = 3
                elif nb >= s2: niv = 2
                
                if niv == 3: st.error(f"🔴 NIVEAU 3 ({nb} abs)")
                elif niv == 2: st.warning(f"🟠 NIVEAU 2 ({nb} abs)")
                else: st.info(f"🟡 NIVEAU 1 ({nb} abs)")

                to_process = df_todo[df_todo["Nom"] == client].sort_values("Date_dt", ascending=False)
                ids_todo = []
                txt = []
                for _, r in to_process.iterrows():
                    ids_todo.append(r['id'])
                    d = r["Date_dt"].strftime("%d/%m") if pd.notnull(r["Date_dt"]) else "?"
                    c = r.get("Cours", "Séance")
                    txt.append(f"- {c} le {d}")
                
                msg = ""
                lbl = "Traité"
                if niv == 2:
                    st.write("**Action : APPEL TÉLÉPHONIQUE**")
                    lbl = "✅ J'ai appelé"
                elif niv == 3:
                    st.write("**Action : CONVOCATION**")
                    tpl = st.session_state.get("msg_p3_tpl", "Bonjour {prenom}, RDV nécessaire ({details}).")
                    msg = tpl.replace("{prenom}", client).replace("{details}", "\n".join(txt))
                    st.text_area("Copier :", value=msg, height=150)
                    lbl = "✅ Convocation envoyée"
                else:
                    st.write("**Action : MAIL**")
                    tpl = st.session_state.get("msg_tpl", "Bonjour {prenom}, absences : {details}.")
                    msg = tpl.replace("{prenom}", client).replace("{details}", "\n".join(txt))
                    st.text_area("Copier :", value=msg, height=150)
                    lbl = "✅ Mail envoyé"

                if st.button(lbl, type="primary"):
                    now = datetime.now().strftime("%Y-%m-%d %H:%M")
                    for pid in ids_todo:
                        try: table.update(pid, {"Traite": True, "Date_Traitement": now})
                        except: pass
                    st.success("Archivé !")
                    st.rerun()

    with tab2:
        df_done = df_work[(df_work["Statut"] == "Absent") & (df_work["Traite"] == True)]
        if not df_done.empty:
            cols = ["Nom", "Date", "Cours"]
            if "Date_Traitement" in df_done.columns:
                cols.append("Date_Traitement")
                df_done = df_done.sort_values("Date_Traitement", ascending=False)
            st.dataframe(df_done[cols], use_container_width=True)
        else:
            st.info("Vide")

# =======================
# 5. MANAGER (CORRIGÉ & COMPLET)
# =======================
def show_manager():
    st.markdown("""
        <style>
        .stMetric { background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 15px; border-radius: 10px; color: #31333F; }
        [data-testid="stMetricLabel"] { font-weight: bold; color: #666; }
        [data-testid="stMetricValue"] { color: #000; }
        </style>
    """, unsafe_allow_html=True)

    st.title("📊 Manager - Pilotage")

    if st.sidebar.text_input("Code Manager", type="password") != MANAGER_PASSWORD:
        st.info("Identifiez-vous à gauche.")
        return

    if df_all.empty:
        st.warning("Aucune donnée.")
        return

    # --- PRÉPARATION ---
    df_ana = df_all.copy()
    if "Date_dt" not in df_ana.columns and "Date" in df_ana.columns:
         df_ana["Date_dt"] = pd.to_datetime(df_ana["Date"], errors='coerce')
    df_ana = df_ana.dropna(subset=["Date_dt"])

    # Nettoyage Heure
    def clean_h(v):
        s = str(v)
        if len(s) > 8 and (" " in s or "T" in s):
            try: return s.replace("T", " ").split(" ")[-1][:5]
            except: return s
        return s
    
    if "Heure" in df_ana.columns: df_ana["Heure"] = df_ana["Heure"].apply(clean_h)
    else: df_ana["Heure"] = "?"
    if "Cours" not in df_ana.columns: df_ana["Cours"] = "Inconnu"

    # Colonnes Temps
    df_ana["Annee"] = df_ana["Date_dt"].dt.year
    df_ana["Mois"] = df_ana["Date_dt"].dt.month
    jours = {0:"Lundi", 1:"Mardi", 2:"Mercredi", 3:"Jeudi", 4:"Vendredi", 5:"Samedi", 6:"Dimanche"}
    df_ana["Jour"] = df_ana["Date_dt"].dt.dayofweek.map(jours)
    df_ana["Jour_Num"] = df_ana["Date_dt"].dt.dayofweek

    # --- FILTRES ---
    st.sidebar.header("📅 Période")
    yrs = sorted(df_ana["Annee"].unique(), reverse=True)
    yr = st.sidebar.selectbox("Année", yrs)
    df_yr = df_ana[df_ana["Annee"] == yr]
    
    mths = sorted(df_yr["Mois"].unique())
    m_list = ["TOUS"] + [pd.to_datetime(f"2022-{m}-01").strftime("%B") for m in mths]
    m_sel = st.sidebar.selectbox("Mois", m_list)
    
    if m_sel == "TOUS": df_filt = df_yr.copy()
    else:
        m_idx = mths[m_list.index(m_sel)-1]
        df_filt = df_yr[df_yr["Mois"] == m_idx].copy()

    # --- CRÉATION DE L'ÉTIQUETTE INTELLIGENTE (COURS + JOUR + HEURE) ---
    # Pour différencier le cours du Lundi de celui du Mercredi
    # Exemple résultat : "Aquafitness (Lundi 12h15)"
    df_filt["Cours_Complet"] = df_filt["Cours"] + " (" + df_filt["Jour"] + " " + df_filt["Heure"] + ")"

    # --- DASHBOARD ---
    tab1, tab2 = st.tabs(["📊 STATISTIQUES", "⚙️ CONFIGURATION"])
    
    with tab1:
        tot = len(df_filt)
        pres = len(df_filt[df_filt["Statut"]=="Présent"])
        absent = len(df_filt[df_filt["Statut"]=="Absent"])
        taux = (pres/tot*100) if tot>0 else 0
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Inscrits", tot)
        c2.metric("Présents", pres, f"{taux:.1f}%")
        c3.metric("Absents", absent, delta_color="inverse")
        
        st.write("---")
        
        # 1. GRAPH EVOLUTION (FRANCAIS)
        st.subheader("📈 Évolution de la Fréquentation")
        if not df_filt.empty:
            daily = df_filt[df_filt["Statut"] == "Présent"].groupby("Date_dt").size()
            st.area_chart(daily, color="#3b82f6")
        
        st.write("---")

        # 2. TOP COURS (DETAILLES) & SEMAINE
        c_g1, c_g2 = st.columns(2)
        with c_g1:
            st.subheader("🔥 Top Cours (Les plus fréquentés)")
            if not df_filt.empty:
                # On utilise la colonne intelligente créée plus haut
                # On compte les présents uniquement pour le succès
                top_data = df_filt[df_filt["Statut"]=="Présent"]["Cours_Complet"].value_counts().head(10)
                st.bar_chart(top_data)
        
        with c_g2:
            st.subheader("📅 Affluence par Jour")
            if not df_filt.empty:
                # Tri forcé Lundi -> Dimanche
                sem = df_filt[df_filt["Statut"]=="Présent"].groupby("Jour").size()
                ordre = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
                sem = sem.reindex(ordre, fill_value=0)
                st.bar_chart(sem, color="#76b900")
        
        st.write("---")

        # 3. TABLEAU DETAILLE
        st.subheader("📋 Détails par Créneau")
        if not df_filt.empty:
            synt = df_filt.groupby(["Jour_Num", "Jour", "Heure", "Cours"]).agg(
                Inscrits=('Nom', 'count'),
                Presents=('Statut', lambda x: (x=='Présent').sum())
            ).reset_index()
            synt["Taux %"] = (synt["Presents"]/synt["Inscrits"]*100).round(1)
            synt.sort_values(["Jour_Num", "Heure"], inplace=True)
            st.dataframe(synt[["Jour", "Heure", "Cours", "Inscrits", "Presents", "Taux %"]], use_container_width=True, hide_index=True)

        st.write("---")

        # 4. LES TOPS CLIENTS
        c_top1, c_top2 = st.columns(2)
        with c_top1:
            st.subheader("🚨 Top 10 Absents")
            if not df_filt.empty:
                top_abs = df_filt[df_filt["Statut"]=="Absent"]["Nom"].value_counts().head(10).reset_index()
                top_abs.columns = ["Nom", "Nb Absences"]
                st.dataframe(top_abs, use_container_width=True, hide_index=True)

        with c_top2:
            st.subheader("🏆 Top 10 Assidus")
            if not df_filt.empty:
                top_pres = df_filt[df_filt["Statut"]=="Présent"]["Nom"].value_counts().head(10).reset_index()
                top_pres.columns = ["Nom", "Nb Présences"]
                st.dataframe(top_pres, use_container_width=True, hide_index=True)

    with tab2:
        c_s, c_m = st.columns(2)
        with c_s:
            st.subheader("Seuils Alertes")
            st.number_input("P1", key="p1_val", value=1)
            st.number_input("P2", key="p2_val", value=3)
            st.number_input("P3", key="p3_val", value=5)
        with c_m:
            st.subheader("Messages")
            st.text_area("P1", key="msg_tpl", value="Bonjour...", height=100)
            st.text_area("P3", key="msg_p3_tpl", value="Convocation...", height=100)
            if st.button("Sauvegarder"): st.success("OK")

# =======================
# 6. NAVIGATION
# =======================
if 'page' not in st.session_state: st.session_state.page = "HUB"

def go(p): st.session_state.page = p; st.rerun()

if st.session_state.page == "HUB":
    st.markdown("<h1 style='text-align:center;'>🏊‍♂️ Piscine Pro</h1>", unsafe_allow_html=True)
    st.write("---")
    c1, c2, c3 = st.columns(3)
    if c1.button("👨‍🏫 MAÎTRE-NAGEUR", use_container_width=True): go("MN")
    if c2.button("💁 RÉCEPTION", use_container_width=True): go("REC")
    if c3.button("📊 MANAGER", use_container_width=True): go("MGR")

elif st.session_state.page == "MN":
    if st.sidebar.button("🏠 Accueil"): go("HUB")
    show_maitre_nageur()

elif st.session_state.page == "REC":
    if st.sidebar.button("🏠 Accueil"): go("HUB")
    show_reception()

elif st.session_state.page == "MGR":
    if st.sidebar.button("🏠 Accueil"): go("HUB")
    show_manager()

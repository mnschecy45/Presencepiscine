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
    st.error(f"Erreur de connexion Airtable (Vérifiez vos clés) : {e}")
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
# 4. RÉCEPTION (CRM)
# =======================
def show_reception():
    st.title("💁 Réception - Gestion Clients")

    if df_all.empty:
        st.warning("Chargement des données...")
        return

    df_work = df_all.copy()
    if "Date_dt" not in df_work.columns and "Date" in df_work.columns:
         df_work["Date_dt"] = pd.to_datetime(df_work["Date"], errors='coerce')
    if "Traite" not in df_work.columns: df_work["Traite"] = False

    tab_todo, tab_hist = st.tabs(["⚡ À TRAITER", "✅ HISTORIQUE"])

    with tab_todo:
        df_todo = df_work[(df_work["Statut"] == "Absent") & (df_work["Traite"] != True)]
        
        if df_todo.empty:
            st.success("🎉 Rien à faire ! Tout est à jour.")
        else:
            st.write(f"**{len(df_todo)} absences** en attente.")
            client_select = st.selectbox("Sélectionner un client", df_todo["Nom"].unique())
            
            if client_select:
                all_abs = df_work[(df_work["Nom"] == client_select) & (df_work["Statut"] == "Absent")]
                nb_total = len(all_abs)
                
                s1 = st.session_state.get("p1_val", 1)
                s2 = st.session_state.get("p2_val", 3)
                s3 = st.session_state.get("p3_val", 5)
                l1 = st.session_state.get("p1_label", "Envoyer un mail")
                l2 = st.session_state.get("p2_label", "Appeler le client")
                l3 = st.session_state.get("p3_label", "Convocation / RDV")
                
                niveau = 1
                label_actuel = l1
                if nb_total >= s3: 
                    niveau = 3
                    label_actuel = l3
                elif nb_total >= s2: 
                    niveau = 2
                    label_actuel = l2
                
                if niveau == 3: st.error(f"🔴 NIVEAU 3 - {label_actuel.upper()} ({nb_total} absences)")
                elif niveau == 2: st.warning(f"🟠 NIVEAU 2 - {label_actuel.upper()} ({nb_total} absences)")
                else: st.info(f"🟡 NIVEAU 1 - {label_actuel.upper()} ({nb_total} absences)")

                to_process = df_todo[df_todo["Nom"] == client_select].sort_values("Date_dt", ascending=False)
                ids_a_traiter = []
                txt_list = []
                for _, row in to_process.iterrows():
                    ids_a_traiter.append(row['id'])
                    d = row["Date_dt"].strftime("%d/%m") if pd.notnull(row["Date_dt"]) else "?"
                    c = row.get("Cours", "Séance")
                    txt_list.append(f"- {c} le {d}")
                
                details_str = "\n".join(txt_list)
                msg_final = ""
                label_btn = f"✅ {label_actuel} (Fait)"
                
                if niveau == 2:
                    st.markdown(f"### 📞 Action : {label_actuel}")
                    st.write("*Script : Bonjour, nous avons noté plusieurs absences. Tout va bien ?*")
                    label_btn = f"✅ J'ai fait : {label_actuel}"
                elif niveau == 3:
                    st.markdown(f"### ✉️ Action : {label_actuel}")
                    tpl = st.session_state.get("msg_p3_tpl", "Bonjour {prenom}, RDV nécessaire ({details}).")
                    msg_final = tpl.replace("{prenom}", client_select).replace("{details}", details_str)
                    st.text_area("Copier :", value=msg_final, height=200)
                    label_btn = f"✅ {label_actuel} envoyé"
                else:
                    st.markdown(f"### 📧 Action : {label_actuel}")
                    tpl = st.session_state.get("msg_tpl", "Bonjour {prenom}, absences : {details}.")
                    msg_final = tpl.replace("{prenom}", client_select).replace("{details}", details_str)
                    st.text_area("Copier :", value=msg_final, height=200)
                    label_btn = f"✅ {label_actuel} envoyé"

                if st.button(label_btn, type="primary"):
                    prog = st.progress(0)
                    now = datetime.now().strftime("%Y-%m-%d %H:%M")
                    for idx, pid in enumerate(ids_a_traiter):
                        try:
                            table.update(pid, {"Traite": True, "Date_Traitement": now})
                            prog.progress((idx+1)/len(ids_a_traiter))
                        except: pass
                    st.success(f"Dossier {client_select} archivé !")
                    st.rerun()

    with tab_hist:
        df_done = df_work[(df_work["Statut"] == "Absent") & (df_work["Traite"] == True)].copy()
        if not df_done.empty:
            cols = ["Nom", "Date", "Cours"]
            if "Date_Traitement" in df_done.columns:
                cols.append("Date_Traitement")
                df_done.sort_values("Date_Traitement", ascending=False, inplace=True)
            st.dataframe(df_done[cols], use_container_width=True)
        else:
            st.info("Vide.")

# =======================
# 5. MANAGER (Pilotage, Semaine, Comparateur)
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
    df_ana["Semaine"] = df_ana["Date_dt"].dt.isocalendar().week
    
    jours = {0:"Lundi", 1:"Mardi", 2:"Mercredi", 3:"Jeudi", 4:"Vendredi", 5:"Samedi", 6:"Dimanche"}
    df_ana["Jour"] = df_ana["Date_dt"].dt.dayofweek.map(jours)
    df_ana["Jour_Num"] = df_ana["Date_dt"].dt.dayofweek
    
    # Étiquette Unique pour Comparaison (Cours + Jour + Heure)
    df_ana["Cours_Complet"] = df_ana["Cours"] + " (" + df_ana["Jour"] + " " + df_ana["Heure"] + ")"

    # ==========================
    # ONGLETS PRINCIPAUX
    # ==========================
    tab1, tab_comp, tab2 = st.tabs(["📊 DASHBOARD", "🚀 ÉVOLUTION & COMPARATEUR", "⚙️ CONFIGURATION"])
    
    # --- TAB 1 : DASHBOARD (Avec Filtres Sidebar) ---
    with tab1:
        st.sidebar.header("📅 Filtres Dashboard")
        yrs = sorted(df_ana["Annee"].unique(), reverse=True)
        yr = st.sidebar.selectbox("Année", yrs)
        df_yr = df_ana[df_ana["Annee"] == yr]
        
        vue_type = st.sidebar.radio("Type de vue", ["Par Mois", "Par Semaine"])
        
        if vue_type == "Par Mois":
            mths = sorted(df_yr["Mois"].unique())
            m_list = ["TOUS"] + [pd.to_datetime(f"2022-{m}-01").strftime("%B") for m in mths]
            m_sel = st.sidebar.selectbox("Choisir le Mois", m_list)
            if m_sel == "TOUS": df_filt = df_yr.copy()
            else:
                m_idx = mths[m_list.index(m_sel)-1]
                df_filt = df_yr[df_yr["Mois"] == m_idx].copy()
        else:
            sems = sorted(df_yr["Semaine"].unique())
            s_list = [f"Semaine {s}" for s in sems]
            s_sel = st.sidebar.selectbox("Choisir la Semaine", s_list)
            sem_num = int(s_sel.split(" ")[1])
            df_filt = df_yr[df_yr["Semaine"] == sem_num].copy()

        # KPIs
        tot = len(df_filt)
        pres = len(df_filt[df_filt["Statut"]=="Présent"])
        absent = len(df_filt[df_filt["Statut"]=="Absent"])
        taux = (pres/tot*100) if tot>0 else 0
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Inscrits", tot)
        c2.metric("Présents", pres, f"{taux:.1f}%")
        c3.metric("Absents", absent, delta_color="inverse")
        
        st.write("---")
        st.subheader("📈 Évolution de la Fréquentation")
        if not df_filt.empty:
            daily = df_filt[df_filt["Statut"] == "Présent"].groupby("Date_dt").size()
            st.area_chart(daily, color="#3b82f6")
        
        st.write("---")
        c_g1, c_g2 = st.columns(2)
        with c_g1:
            st.subheader("🔥 Top Cours")
            if not df_filt.empty:
                top_data = df_filt[df_filt["Statut"]=="Présent"]["Cours_Complet"].value_counts().head(10)
                st.bar_chart(top_data)
        with c_g2:
            st.subheader("📅 Affluence par Jour")
            if not df_filt.empty:
                sem = df_filt[df_filt["Statut"]=="Présent"].groupby("Jour").size()
                ordre_imposé = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
                sem = sem.reindex(ordre_imposé, fill_value=0)
                st.bar_chart(sem, color="#76b900")
        
        st.write("---")
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

    # --- TAB 2 : EVOLUTION & COMPARATEUR (LE NOUVEAU JOUET) ---
    with tab_comp:
        st.header("🚀 Analyse Avancée")
        sub_tab1, sub_tab2 = st.tabs(["📉 Suivi d'un Cours (Évolution)", "🆚 Comparateur Périodes"])

        # 1. EVOLUTION D'UN COURS PRECIS
        with sub_tab1:
            st.info("Visualisez la courbe de vie d'un cours spécifique (ex: Est-ce que le Lundi 12h se vide ?).")
            # Liste unique des cours (Cours + Jour + Heure)
            liste_cours_uniques = sorted(df_ana["Cours_Complet"].unique())
            cours_choisi = st.selectbox("Sélectionnez le cours à analyser :", liste_cours_uniques)
            
            if cours_choisi:
                # On filtre les données pour ce cours précis
                df_cours = df_ana[df_ana["Cours_Complet"] == cours_choisi].sort_values("Date_dt")
                
                if not df_cours.empty:
                    # On groupe par date pour avoir le nb d'inscrits et de présents par séance
                    evo = df_cours.groupby("Date_dt").agg(
                        Inscrits=('Nom', 'count'),
                        Presents=('Statut', lambda x: (x=='Présent').sum())
                    )
                    st.line_chart(evo)
                    st.write("Données brutes :")
                    st.dataframe(evo.sort_index(ascending=False), use_container_width=True)
                else:
                    st.warning("Pas assez de données pour ce cours.")

        # 2. COMPARATEUR A vs B
        with sub_tab2:
            st.info("Comparez la performance de deux périodes (ex: Semaine 44 vs Semaine 45).")
            
            type_comp = st.radio("Comparer :", ["Deux Semaines", "Deux Mois"], horizontal=True)
            
            col_a, col_b = st.columns(2)
            
            df_A = pd.DataFrame()
            df_B = pd.DataFrame()
            label_A = ""
            label_B = ""

            if type_comp == "Deux Semaines":
                liste_semaines = sorted(df_ana["Semaine"].unique())
                with col_a:
                    sem_A = st.selectbox("Période A (Semaine)", liste_semaines, index=len(liste_semaines)-2 if len(liste_semaines)>1 else 0)
                    df_A = df_ana[df_ana["Semaine"] == sem_A]
                    label_A = f"Semaine {sem_A}"
                with col_b:
                    sem_B = st.selectbox("Période B (Semaine)", liste_semaines, index=len(liste_semaines)-1 if len(liste_semaines)>0 else 0)
                    df_B = df_ana[df_ana["Semaine"] == sem_B]
                    label_B = f"Semaine {sem_B}"
            else:
                liste_mois = sorted(df_ana["Mois"].unique())
                with col_a:
                    mois_A = st.selectbox("Période A (Mois)", liste_mois)
                    df_A = df_ana[df_ana["Mois"] == mois_A]
                    label_A = f"Mois {mois_A}"
                with col_b:
                    mois_B = st.selectbox("Période B (Mois)", liste_mois)
                    df_B = df_ana[df_ana["Mois"] == mois_B]
                    label_B = f"Mois {mois_B}"

            st.write("---")
            
            # CALCUL DES METRIQUES
            if not df_A.empty and not df_B.empty:
                # KPI Globaaux
                pres_A = len(df_A[df_A["Statut"]=="Présent"])
                pres_B = len(df_B[df_B["Statut"]=="Présent"])
                delta_pres = pres_B - pres_A
                
                remp_A = (pres_A / len(df_A) * 100) if len(df_A) > 0 else 0
                remp_B = (pres_B / len(df_B) * 100) if len(df_B) > 0 else 0
                delta_remp = remp_B - remp_A

                c1, c2 = st.columns(2)
                c1.metric(f"Présents ({label_A})", pres_A)
                c2.metric(f"Présents ({label_B})", pres_B, delta=delta_pres)
                
                st.write("---")
                st.subheader("Comparaison par Cours")
                
                # On prépare les données par cours pour A
                stats_A = df_A[df_A["Statut"]=="Présent"].groupby("Cours_Complet").size().reset_index(name="Présents A")
                # On prépare les données par cours pour B
                stats_B = df_B[df_B["Statut"]=="Présent"].groupby("Cours_Complet").size().reset_index(name="Présents B")
                
                # On fusionne les deux tableaux
                comparatif = pd.merge(stats_A, stats_B, on="Cours_Complet", how="outer").fillna(0)
                comparatif["Ecart"] = comparatif["Présents B"] - comparatif["Présents A"]
                
                st.dataframe(comparatif.set_index("Cours_Complet").style.background_gradient(subset=["Ecart"], cmap="RdYlGn"), use_container_width=True)

            else:
                st.warning("Sélectionnez des périodes valides contenant des données.")


    # --- TAB 3 : CONFIGURATION (Restaurée) ---
    with tab2:
        st.header("⚙️ Paramètres des Relances")
        col_seuils, col_msg = st.columns([1, 1])

        with col_seuils:
            st.subheader("1. Paliers & Actions")
            st.markdown("---")
            c1a, c1b = st.columns([1, 2])
            st.number_input("Seuil P1 (Nb Absences)", key="p1_val", value=1, min_value=1)
            st.text_input("Nom Action P1", key="p1_label", value="Envoyer un mail")
            
            st.markdown("---")
            c2a, c2b = st.columns([1, 2])
            st.number_input("Seuil P2 (Nb Absences)", key="p2_val", value=3, min_value=1)
            st.text_input("Nom Action P2", key="p2_label", value="Appeler le client")
            
            st.markdown("---")
            c3a, c3b = st.columns([1, 2])
            st.number_input("Seuil P3 (Nb Absences)", key="p3_val", value=5, min_value=1)
            st.text_input("Nom Action P3", key="p3_label", value="Convocation / RDV")

        with col_msg:
            st.subheader("2. Modèles de Messages")
            st.markdown("**✉️ Message P1 (Mail)**")
            default_p1 = "Bonjour {prenom},\n\nSauf erreur de notre part, nous avons relevé les absences suivantes :\n{details}\n\nAfin de ne pas perdre le bénéfice de votre progression, merci de nous confirmer votre présence pour la prochaine séance.\n\nCordialement,\nL'équipe Piscine."
            st.text_area("Template P1", key="msg_tpl", value=default_p1, height=250)

            st.markdown("---")
            st.markdown("**✉️ Message P3 (Convocation)**")
            default_p3 = "Bonjour {prenom},\n\nSuite à de nombreuses absences ({details}), nous souhaiterions faire un point avec vous.\nMerci de passer à l'accueil pour fixer un rendez-vous."
            st.text_area("Template P3", key="msg_p3_tpl", value=default_p3, height=150)

        if st.button("💾 Sauvegarder la configuration", type="primary"):
            st.success("Configuration enregistrée avec succès !")

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

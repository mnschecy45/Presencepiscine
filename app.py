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
    
    # On récupère TOUT (y compris les ID pour pouvoir modifier les lignes)
    records = table.all()
    
    if records:
        data = []
        for r in records:
            row = r['fields']
            row['id'] = r['id']  # On garde l'ID pour la Réception
            data.append(row)
        df_all = pd.DataFrame(data)
        
        # Nettoyage des dates
        if "Date" in df_all.columns:
            df_all["Date_dt"] = pd.to_datetime(df_all["Date"], errors='coerce')
    else:
        df_all = pd.DataFrame()
except Exception as e:
    st.error(f"Erreur de connexion Airtable (Vérifiez vos clés) : {e}")
    df_all = pd.DataFrame()

# =======================
# 2. FONCTIONS UTILES (Sauvegarde & PDF)
# =======================
def save_data_to_cloud(df_new):
    """ Envoie les nouvelles présences vers Airtable """
    progress_bar = st.progress(0)
    total = len(df_new)
    
    for i, row in df_new.iterrows():
        try:
            statut_final = "Absent" if row["Absent"] else "Présent"
            
            # Date format texte YYYY-MM-DD
            if isinstance(row["Date"], (date, datetime)):
                date_str = row["Date"].strftime("%Y-%m-%d")
            else:
                date_str = str(row["Date"])

            record = {
                "Nom": row["Nom"],
                "Statut": statut_final, 
                "Date": date_str,
                "Cours": row["Cours"],
                "Heure": row["Heure"],
                "Traite": False # Par défaut, ce n'est pas traité
            }
            
            table.create(record)
            progress_bar.progress((i + 1) / total)
            
        except Exception as e:
            st.error(f"Erreur envoi ligne {i}: {e}")

    progress_bar.empty()
    st.toast("Sauvegarde terminée !", icon="☁️")

def parse_pdf_complete(file_bytes):
    """ Lit le PDF et extrait les noms, cours et heures """
    rows = []
    ignore = ["TCPDF", "www.", "places", "réservées", "disponibles", "ouvertes", "le ", " à ", "Page ", "Généré"]
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                txt = page.extract_text()
                if not txt: continue
                lines = txt.splitlines()
                
                # 1. Trouver la date
                d_str = ""
                for l in lines[:15]:
                    m = re.search(r"\d{2}/\d{2}/\d{4}", l)
                    if m: d_str = m.group(0); break
                s_date = datetime.strptime(d_str, "%d/%m/%Y").date() if d_str else date.today()
                
                # 2. Trouver Cours et Heure
                c_name, h_deb = "Cours Inconnu", "00h00"
                for l in lines[:15]:
                    ts = re.findall(r"\d{1,2}h\d{2}", l)
                    if ts:
                        h_deb = ts[0]
                        c_name = l[:l.index(ts[0])].strip()
                        break
                
                # 3. Trouver les Noms
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
# 3. INTERFACE MAÎTRE-NAGEUR
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
            date_str = d_obj.strftime('%d/%m/%Y') if isinstance(d_obj, (date, datetime)) else str(d_obj)
            st.info(f"📅 **{date_str}** | {df['Cours'].iloc[0]} ({df['Heure'].iloc[0]})")

            # Actions rapides
            c1, c2 = st.columns(2)
            if c1.button("✅ TOUT PRÉSENT"):
                for i in range(len(df)): st.session_state[f"cb_{i}"] = True
                st.rerun()
            if c2.button("❌ TOUT ABSENT"):
                for i in range(len(df)): st.session_state[f"cb_{i}"] = False
                st.rerun()

            st.write("---")

            # Liste Élèves
            for idx, row in df.iterrows():
                key = f"cb_{idx}"
                if key not in st.session_state: st.session_state[key] = False
                
                bg = "#dcfce7" if st.session_state[key] else "#fee2e2"
                col_n, col_c = st.columns([4, 1])
                col_n.markdown(f"<div style='padding:10px; background:{bg}; border-radius:5px;'><b>{row['Nom']} {row['Prenom']}</b></div>", unsafe_allow_html=True)
                st.checkbox("Présent", key=key, label_visibility="collapsed")
                df.at[idx, "Absent"] = not st.session_state[key]

            st.write("---")
            
            # Ajout Manuel
            with st.expander("➕ Ajouter un client manuellement"):
                with st.form("add_manual"):
                    nom_m = st.text_input("Nom Client").upper()
                    if st.form_submit_button("Ajouter"):
                        new_row = df.iloc[0].copy()
                        new_row["Nom"] = nom_m
                        new_row["Prenom"] = "(Manuel)"
                        new_row["Manuel"] = True
                        new_row["Absent"] = False
                        st.session_state.df_appel = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                        st.rerun()

            # Validation Finale
            nb_presents = len(df[df["Absent"]==False])
            st.metric("Clients dans l'eau", nb_presents)
            
            if st.button("💾 ENREGISTRER DÉFINITIVEMENT", type="primary"):
                save_data_to_cloud(df)
                st.session_state.appel_termine = True
                st.rerun()

# =======================
# 4. INTERFACE RÉCEPTION (CRM)
# =======================
def show_reception():
    st.title("💁 Réception - Gestion Clients")

    if df_all.empty:
        st.warning("Chargement des données...")
        return

    # Prépa données
    df_work = df_all.copy()
    if "Date_dt" not in df_work.columns and "Date" in df_work.columns:
         df_work["Date_dt"] = pd.to_datetime(df_work["Date"], errors='coerce')
    if "Traite" not in df_work.columns: df_work["Traite"] = False

    tab_todo, tab_hist = st.tabs(["⚡ À TRAITER", "✅ HISTORIQUE"])

    # --- A TRAITER ---
    with tab_todo:
        # Filtre : Absent ET Pas Traité
        df_todo = df_work[(df_work["Statut"] == "Absent") & (df_work["Traite"] != True)]
        
        if df_todo.empty:
            st.success("🎉 Rien à faire ! Tout est à jour.")
        else:
            st.write(f"**{len(df_todo)} absences** en attente.")
            client_select = st.selectbox("Sélectionner un client", df_todo["Nom"].unique())
            
            if client_select:
                # 1. Calcul Niveau (Sur historique complet)
                all_abs = df_work[(df_work["Nom"] == client_select) & (df_work["Statut"] == "Absent")]
                nb_total = len(all_abs)
                
                s1 = st.session_state.get("p1_val", 1)
                s2 = st.session_state.get("p2_val", 3)
                s3 = st.session_state.get("p3_val", 5)
                
                niveau = 1
                if nb_total >= s3: niveau = 3
                elif nb_total >= s2: niveau = 2
                
                # Alertes visuelles
                if niveau == 3: st.error(f"🔴 NIVEAU 3 - CONVOCATION ({nb_total} absences)")
                elif niveau == 2: st.warning(f"🟠 NIVEAU 2 - APPEL ({nb_total} absences)")
                else: st.info(f"🟡 NIVEAU 1 - MAIL ({nb_total} absences)")

                # 2. Détails (seulement les non traités)
                to_process = df_todo[df_todo["Nom"] == client_select].sort_values("Date_dt", ascending=False)
                ids_a_traiter = []
                txt_list = []
                
                for _, row in to_process.iterrows():
                    ids_a_traiter.append(row['id'])
                    d = row["Date_dt"].strftime("%d/%m") if pd.notnull(row["Date_dt"]) else "?"
                    c = row.get("Cours", "Séance")
                    txt_list.append(f"- {c} le {d}")
                
                details_str = "\n".join(txt_list)

                # 3. Action
                msg_final = ""
                label_btn = "✅ Traité"
                
                if niveau == 2:
                    st.markdown("### 📞 Action : Appeler")
                    st.write("*Script : Bonjour, nous avons noté plusieurs absences. Tout va bien ?*")
                    label_btn = "✅ J'ai appelé le client"
                elif niveau == 3:
                    st.markdown("### ✉️ Action : Convocation")
                    tpl = st.session_state.get("msg_p3_tpl", "Bonjour {prenom}, RDV nécessaire ({details}).")
                    msg_final = tpl.replace("{prenom}", client_select).replace("{details}", details_str)
                    st.text_area("Copier :", value=msg_final, height=150)
                    label_btn = "✅ Convocation envoyée"
                else:
                    st.markdown("### 📧 Action : Mail")
                    tpl = st.session_state.get("msg_tpl", "Bonjour {prenom}, absences : {details}.")
                    msg_final = tpl.replace("{prenom}", client_select).replace("{details}", details_str)
                    st.text_area("Copier :", value=msg_final, height=150)
                    label_btn = "✅ Mail envoyé"

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

    # --- HISTORIQUE ---
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
# 5. INTERFACE MANAGER (Analytique)
# =======================
def show_manager():
    # Style Clair
    st.markdown("""
        <style>
        .stMetric { background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 15px; border-radius: 10px; color: #31333F; }
        [data-testid="stMetricLabel"] { font-weight: bold; color: #666; }
        [data-testid="stMetricValue"] { color: #000; }
        </style>
    """, unsafe_allow_html=True)

    st.title("📊 Manager - Pilotage")

    if st.sidebar.text_input("Mot de passe", type="password") != MANAGER_PASSWORD:
        st.info("Identifiez-vous à gauche (Menu >).")
        return

    if df_all.empty:
        st.warning("Aucune donnée.")
        return

    # Prépa
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

    # Filtres
    st.sidebar.header("📅 Filtres")
    yrs = sorted(df_ana["Annee"].unique(), reverse=True)
    yr = st.sidebar.selectbox("Année", yrs)
    df_yr = df_ana[df_ana["Annee"] == yr]
    
    mths = sorted(df_yr["Mois"].unique())
    m_list = ["TOUS"] + [pd.to_datetime(f"2022-{m}-01").strftime("%B") for m in mths]
    m_sel = st.sidebar.selectbox("Mois", m_list)
    
    if m_sel == "TOUS": df_filt = df_yr
    else:
        m_idx = mths[m_list.index(m_sel)-1]
        df_filt = df_yr[df_yr["Mois"] == m_idx]

    # Dashboard
    tab1, tab2 = st.tabs(["📊 STATS", "⚙️ CONFIG"])
    
    with tab1:
        tot = len(df_filt)
        pres = len(df_filt[df_filt["Statut"]=="Présent"])
        absent = len(df_filt[df_filt["Statut"]=="Absent"])
        taux = (pres/tot*100) if tot>0 else 0
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Inscrits", tot)
        c2.metric("Présents", pres, f"{taux:.1f}%")
        c3.metric("Absents", absent, delta_color="inverse")
        c4.metric("CA Estimé", f"{pres * 15} €")
        
        st.write("---")
        st.subheader("Détails par Créneau")
        if not df_filt.empty:
            synt = df_filt.groupby(["Jour_Num", "Jour", "Heure", "Cours"]).agg(
                Inscrits=('Nom', 'count'),
                Presents=('Statut', lambda x: (x=='Présent').sum())
            ).reset_index()
            synt["Taux %"] = (synt["Presents"]/synt["Inscrits"]*100).round(1)
            synt.sort_values(["Jour_Num", "Heure"], inplace=True)
            st.dataframe(synt[["Jour", "Heure", "Cours", "Inscrits", "Presents", "Taux %"]], use_container_width=True, hide_index=True)
        
        c_g1, c_g2 = st.columns(2)
        with c_g1:
            st.subheader("Top Cours")
            if not df_filt.empty: st.bar_chart(df_filt["Cours"].value_counts())
        with c_g2:
            st.subheader("Semaine")
            if not df_filt.empty:
                sem = df_filt.groupby("Jour").size()
                ordre = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
                sem = sem.reindex(ordre, fill_value=0)
                st.bar_chart(sem, color="#76b900")

    with tab2:
        c_s, c_m = st.columns(2)
        with c_s:
            st.subheader("Seuils")
            st.number_input("P1", key="p1_val", value=1)
            st.number_input("P2", key="p2_val", value=3)
            st.number_input("P3", key="p3_val", value=5)
        with c_m:
            st.subheader("Messages")
            st.text_area("P1", key="msg_tpl", value="Bonjour...", height=100)
            st.text_area("P3", key="msg_p3_tpl", value="Convocation...", height=100)
            if st.button("Sauvegarder"): st.success("OK")

# =======================
# 6. NAVIGATION PRINCIPALE
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

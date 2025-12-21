import streamlit as st
import pandas as pd
import pdfplumber
import re
import io
from datetime import datetime, date
from pyairtable import Api  # <--- On remplace GSheets par Airtable

# =======================
# 0. TES CLES AIRTABLE (A REMPLIR ICI)
# =======================
API_TOKEN = "pat85co2rWjG48EDz.e6e628e1b5da543271388625e0006a0186a2e424ff7a3ae6e146508794f8edbd" # Ton token
BASE_ID = "app390ytx6oa2rbge"    # Ton ID de base
TABLE_NAME = "Presences"             # Nom de l'onglet

# =======================
# 1. CONFIGURATION GÉNÉRALE
# =======================
st.set_page_config(page_title="Piscine Pro - Gestion Cloud", layout="wide", page_icon="🏊‍♂️")

MANAGER_PASSWORD = st.secrets.get("MANAGER_PASSWORD", "manager")

# --- CONNEXION AIRTABLE ---
# --- CONNEXION AIRTABLE ET CHARGEMENT ---
try:
    api = Api(API_TOKEN)
    table = api.table(BASE_ID, TABLE_NAME)
    
    # On récupère TOUT (y compris les ID secrets des lignes)
    records = table.all()
    
    if records:
        data = []
        for r in records:
            row = r['fields']
            row['id'] = r['id']  # <--- C'est ça la clé magique pour modifier ensuite !
            data.append(row)
        df_all = pd.DataFrame(data)
        
        # Nettoyage des dates
        if "Date" in df_all.columns:
            df_all["Date_dt"] = pd.to_datetime(df_all["Date"], errors='coerce')
    else:
        df_all = pd.DataFrame()
except Exception as e:
    st.error(f"Erreur de connexion Airtable : {e}")
    df_all = pd.DataFrame()

# =======================
# 2. LOGIQUE DE SAUVEGARDE & PDF
# =======================
def save_data_to_cloud(df_new):
    """
    Envoie les nouvelles lignes vers Airtable une par une.
    """
    progress_bar = st.progress(0)
    total = len(df_new)
    
    for i, row in df_new.iterrows():
        try:
            # On prépare la ligne pour Airtable
            statut_final = "Absent" if row["Absent"] else "Présent"
            
            # Conversion de la date pour Airtable
            if isinstance(row["Date"], (date, datetime)):
                date_str = row["Date"].strftime("%Y-%m-%d")
            else:
                date_str = str(row["Date"])

            # --- C'EST ICI QUE CA SE JOUE ---
            record = {
                "Nom": row["Nom"],
                "Statut": statut_final, 
                "Date": date_str,
                "Cours": row["Cours"],  # <--- J'ai enlevé le # devant
                "Heure": row["Heure"]   # <--- J'ai enlevé le # devant
            }
            
            # Envoi vers Airtable
            table.create(record)
            
            # Mise à jour barre de progression
            progress_bar.progress((i + 1) / total)
            
        except Exception as e:
            st.error(f"Erreur lors de l'enregistrement de {row['Nom']}: {e}")

    progress_bar.empty()
    st.toast("Enregistrement Airtable terminé !", icon="☁️")

def parse_pdf_complete(file_bytes):
    rows = []
    ignore_list = ["TCPDF", "www.", "places", "réservées", "disponibles", "ouvertes", "le ", " à ", "Page ", "Généré"]
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for idx, page in enumerate(pdf.pages):
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
                    if "N° réservation" in l:
                        start_index = i + 1
                        break
                for l in lines[start_index:]:
                    if not l.strip() or any(x in l for x in ignore_list):
                        continue
                    l_clean = re.sub(r'\d+', '', l).strip()
                    l_clean = re.sub(r'\s+', ' ', l_clean)
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
    st.markdown("<div id='top'></div>", unsafe_allow_html=True)
    st.title("👨‍🏫 Appel Bassin")
    
    if st.session_state.get("appel_termine", False):
        st.success("✅ Appel enregistré dans Airtable !")
        if st.button("Faire un nouvel appel"):
            # On nettoie tout pour le nouvel appel
            for key in list(st.session_state.keys()):
                if key.startswith("cb_") or key == "df_appel":
                    del st.session_state[key]
            st.session_state.appel_termine = False
            st.rerun()
        return

    up = st.file_uploader("Charger le PDF d'appel", type=["pdf"])
    
    # Si on charge un nouveau fichier, on nettoie les anciennes cases
    if up:
        if 'current_file' not in st.session_state or st.session_state.current_file != up.name:
            st.session_state.current_file = up.name
            for key in list(st.session_state.keys()):
                if key.startswith("cb_"):
                    del st.session_state[key]
            st.session_state.df_appel = parse_pdf_complete(up.read())

        df = st.session_state.df_appel
        
        # Affichage Jour + Date
        if not df.empty:
            d_obj = df['Date'].iloc[0]
            jours_fr = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
            # Gestion sécurité si d_obj n'est pas une date
            if isinstance(d_obj, (date, datetime)):
                date_complete = f"{jours_fr[d_obj.weekday()]} {d_obj.strftime('%d/%m/%Y')}"
            else:
                date_complete = str(d_obj)

            st.info(f"📅 **{date_complete}** | {df['Cours'].iloc[0]} à {df['Heure'].iloc[0]}")

            # --- ACTIONS RAPIDES ---
            c1, c2, c3 = st.columns([1, 1, 1])
            if c1.button("✅ TOUT PRÉSENT", use_container_width=True):
                for i in range(len(df)):
                    st.session_state[f"cb_{i}"] = True
                st.rerun()
                
            if c2.button("❌ TOUT ABSENT", use_container_width=True):
                for i in range(len(df)):
                    st.session_state[f"cb_{i}"] = False
                st.rerun()
                
            c3.markdown("<p style='text-align:center;'><a href='#bottom'>⬇️ Aller au résumé</a></p>", unsafe_allow_html=True)

            st.write("---")

            # --- LISTE DES ÉLÈVES ---
            for idx, row in df.iterrows():
                key = f"cb_{idx}"
                # Initialisation par défaut si la clé n'existe pas
                if key not in st.session_state:
                    st.session_state[key] = False
                
                # La couleur suit strictement l'état de la session_state
                bg = "#dcfce7" if st.session_state[key] else "#fee2e2"
                
                col_n, col_c = st.columns([4, 1])
                col_n.markdown(f"""
                    <div style='padding:12px; background:{bg}; color:black; border-radius:8px; margin-bottom:5px; border:1px solid #ccc;'>
                        <strong>{row['Nom']} {row['Prenom']}</strong>
                    </div>
                """, unsafe_allow_html=True)
                
                # Utilisation du paramètre 'value' pour forcer l'affichage synchronisé
                st.checkbox("P", key=key, label_visibility="collapsed")
                df.at[idx, "Absent"] = not st.session_state[key]

            # Ajout manuel
            st.write("---")
            with st.expander("➕ AJOUTER UN ÉLÈVE HORS PDF"):
                with st.form("form_ajout", clear_on_submit=True):
                    nom_m = st.text_input("Nom").upper()
                    prenom_m = st.text_input("Prénom")
                    if st.form_submit_button("Valider"):
                        if nom_m and prenom_m:
                            nouveau = {
                                "Date": df['Date'].iloc[0], "Cours": df['Cours'].iloc[0], "Heure": df['Heure'].iloc[0],
                                "Nom": nom_m, "Prenom": prenom_m, "Absent": False, "Manuel": True, "Session_ID": df['Session_ID'].iloc[0]
                            }
                            st.session_state.df_appel = pd.concat([df, pd.DataFrame([nouveau])], ignore_index=True)
                            st.rerun()

            st.markdown("<div id='bottom'></div>", unsafe_allow_html=True)
            st.write("---")
            
            # Résumé
            presents = len(df[df["Absent"] == False])
            st.subheader("📋 Résumé")
            r1, r2, r3 = st.columns(3)
            r1.metric("Inscrits", len(df[df["Manuel"]==False]))
            r2.metric("Absents", len(df[df["Absent"]==True]), delta_color="inverse")
            r3.metric("DANS L'EAU", presents)

            if st.button("💾 ENREGISTRER DÉFINITIVEMENT", type="primary", use_container_width=True):
                save_data_to_cloud(df)
                st.session_state.appel_termine = True
                st.rerun()
            
            st.markdown("<p style='text-align:center;'><a href='#top'>⬆️ Remonter en haut</a></p>", unsafe_allow_html=True)

# =======================
# 4. RÉCEPTION & MANAGER
# =======================
def show_reception():
    st.title("💁 Réception")
    s = st.text_input("🔎 Rechercher par Nom")
    if s and not df_all.empty:
        # On vérifie que les colonnes existent dans Airtable
        cols_to_search = []
        if "Nom" in df_all.columns: cols_to_search.append("Nom")
        if "Prenom" in df_all.columns: cols_to_search.append("Prenom")
        
        if cols_to_search:
            mask = pd.DataFrame(False, index=df_all.index, columns=['match'])
            for col in cols_to_search:
                mask['match'] |= df_all[col].astype(str).str.contains(s, case=False, na=False)
            
            res = df_all[mask['match']]
            
            cols_show = ["Date", "Statut"] # On adapte aux colonnes Airtable
            if "Cours" in df_all.columns: cols_show.append("Cours")
            
            st.dataframe(res[cols_show].sort_values("Date", ascending=False), use_container_width=True)
    elif df_all.empty:
        st.info("La base de données est vide ou inaccessible.")

# =======================
# 4. ESPACE MANAGER (VERSION PRO CONFIG P1/P2/P3)
# =======================
def show_manager():
    # CSS Pro
    st.markdown("""
        <style>
        .stMetric { background-color: #0E1117; border: 1px solid #303030; padding: 15px; border-radius: 5px; }
        </style>
    """, unsafe_allow_html=True)

    st.title("📊 Manager")
    
    password = st.sidebar.text_input("🔒 Code Manager", type="password")
    if password != MANAGER_PASSWORD:
        st.info("Mot de passe requis.")
        return

    if df_all.empty:
        st.warning("Base de données vide.")
        return

    # Préparation
    df_work = df_all.copy()
    if "Date_dt" not in df_work.columns and "Date" in df_work.columns:
         df_work["Date_dt"] = pd.to_datetime(df_work["Date"], errors='coerce')
    
    # Message par défaut
    default_msg = """Bonjour {prenom},

Sauf erreur de notre part, nous avons relevé les absences suivantes :
{details}

Merci de nous confirmer votre présence pour la prochaine séance.

Cordialement,
L'équipe Piscine."""

    # --- ONGLETS ---
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Dashboard", "🚨 A TRAITER", "✅ Historique Traité", "⚙️ Config"])

    # ==========================
    # TAB 1 : DASHBOARD
    # ==========================
    with tab1:
        st.subheader("Vue d'ensemble")
        nb_total = len(df_work)
        nb_abs = len(df_work[df_work["Statut"] == "Absent"])
        # On compte combien sont traitées (la colonne Traite existe et est vraie)
        if "Traite" in df_work.columns:
            nb_traites = len(df_work[(df_work["Statut"] == "Absent") & (df_work["Traite"] == True)])
        else:
            nb_traites = 0
            
        nb_a_traiter = nb_abs - nb_traites
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Absences", nb_abs)
        c2.metric("Déjà Traitées", nb_traites)
        c3.metric("Reste à faire", nb_a_traiter, delta_color="inverse")

    # ==========================
    # TAB 2 : A TRAITER (Le cœur du système)
    # ==========================
    with tab2:
        st.subheader("⚡ Absences nécessitant une action")
        
        # 1. On filtre : Statut Absent ET (Traite est vide ou Faux)
        # On gère le cas où la colonne n'existe pas encore ou contient des vides
        if "Traite" not in df_work.columns:
            df_work["Traite"] = False # On crée la colonne virtuellement si elle manque
            
        # La condition magique : Absent ET (Pas Traité)
        df_todo = df_work[ (df_work["Statut"] == "Absent") & (df_work["Traite"] != True) ]
        
        if not df_todo.empty:
            # On liste les gens qui ont des absences à traiter
            clients_a_traiter = df_todo["Nom"].unique()
            client_select = st.selectbox("Sélectionner un client", clients_a_traiter)
            
            if client_select:
                # --- CALCUL DU NIVEAU (Basé sur TOUTES les absences, même traitées) ---
                # C'est important : si c'est sa 5ème absence, même si les 4 premières sont traitées, il est P3.
                toutes_absences_client = df_work[(df_work["Nom"] == client_select) & (df_work["Statut"] == "Absent")]
                total_abs = len(toutes_absences_client)
                
                # Récup des seuils
                s1 = st.session_state.get("p1_val", 1)
                s2 = st.session_state.get("p2_val", 3)
                s3 = st.session_state.get("p3_val", 5)
                
                if total_abs >= s3: niv_txt = f"🔴 P3 ({st.session_state.get('p3_label', 'Convocation')})"
                elif total_abs >= s2: niv_txt = f"🟠 P2 ({st.session_state.get('p2_label', 'Appel')})"
                elif total_abs >= s1: niv_txt = f"🟡 P1 ({st.session_state.get('p1_label', 'Mail')})"
                else: niv_txt = "OK"

                st.info(f"**Client :** {client_select} | **Niveau Global :** {niv_txt} ({total_abs} abs. totales)")
                
                # --- DÉTAILS DES ABSENCES A TRAITER (Seulement les nouvelles) ---
                # On récupère seulement les lignes "à faire" pour ce client
                absences_a_traiter_client = df_todo[df_todo["Nom"] == client_select].sort_values("Date_dt", ascending=False)
                
                lignes_details = []
                ids_a_traiter = [] # On stocke les ID pour pouvoir les cocher
                
                for _, row in absences_a_traiter_client.iterrows():
                    ids_a_traiter.append(row['id']) # On garde l'ID précieusement
                    
                    # Mise en forme date/heure
                    d_str = row["Date_dt"].strftime("%d/%m/%Y") if pd.notnull(row["Date_dt"]) else "Date ?"
                    h_str = row.get("Heure") if pd.notnull(row.get("Heure")) else ""
                    # Nettoyage heure si c'est une date complète
                    if h_str and len(str(h_str)) > 5: 
                        try: h_str = pd.to_datetime(h_str).strftime("%Hh%M")
                        except: pass
                    
                    c_str = row.get("Cours", "Séance")
                    if pd.isnull(c_str) or c_str == "": c_str = "Séance"
                    
                    lignes_details.append(f"- {c_str} le {d_str} {h_str}")

                txt_details = "\n".join(lignes_details)
                
                # --- PRÉPARATION MESSAGE ---
                tpl = st.session_state.get("msg_tpl", default_msg)
                msg_final = tpl.replace("{prenom}", client_select).replace("{details}", txt_details)
                
                st.text_area("Message à envoyer :", value=msg_final, height=200)
                
                # --- BOUTON D'ACTION ---
                if st.button(f"✅ Marquer {len(ids_a_traiter)} absences comme TRAITÉES"):
                    # C'est ici qu'on écrit dans Airtable
                    progress = st.progress(0)
                    for idx, id_airtable in enumerate(ids_a_traiter):
                        try:
                            # On met à jour la ligne dans Airtable en cochant "Traite"
                            table.update(id_airtable, {"Traite": True})
                            progress.progress((idx + 1) / len(ids_a_traiter))
                        except Exception as e:
                            st.error(f"Erreur update : {e}")
                    
                    st.success(f"Dossier {client_select} mis à jour ! Il va disparaître de la liste.")
                    import time
                    time.sleep(1)
                    st.rerun()

        else:
            st.success("🎉 Rien à faire ! Toutes les absences ont été traitées.")

    # ==========================
    # TAB 3 : HISTORIQUE (Ceux qu'on a déjà faits)
    # ==========================
    with tab3:
        st.subheader("✅ Historique des traitements")
        if "Traite" in df_work.columns:
            df_done = df_work[(df_work["Statut"] == "Absent") & (df_work["Traite"] == True)]
            if not df_done.empty:
                st.dataframe(df_done[["Nom", "Date", "Cours", "Heure"]].sort_values("Date", ascending=False), use_container_width=True)
            else:
                st.info("Aucun historique pour l'instant.")

    # ==========================
    # TAB 4 : CONFIG
    # ==========================
    with tab4:
        st.header("⚙️ Config")
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Seuils")
            p1 = st.number_input("P1", value=st.session_state.get("p1_val", 1))
            l1 = st.text_input("Label P1", value=st.session_state.get("p1_label", "Mail"))
            p2 = st.number_input("P2", value=st.session_state.get("p2_val", 3))
            l2 = st.text_input("Label P2", value=st.session_state.get("p2_label", "Tel"))
            p3 = st.number_input("P3", value=st.session_state.get("p3_val", 5))
            l3 = st.text_input("Label P3", value=st.session_state.get("p3_label", "RDV"))
            if st.button("Save Seuils"):
                st.session_state.p1_val = p1; st.session_state.p1_label = l1
                st.session_state.p2_val = p2; st.session_state.p2_label = l2
                st.session_state.p3_val = p3; st.session_state.p3_label = l3
                st.success("OK")
        with c2:
            st.subheader("Message")
            tpl = st.text_area("Template", value=st.session_state.get("msg_tpl", default_msg), height=300)
            if st.button("Save Msg"):
                st.session_state.msg_tpl = tpl
                st.success("OK")

# =======================
# 5. HUB D'ACCUEIL
# =======================
def show_main_hub():
    st.markdown("<h1 style='text-align: center;'>🏊‍♂️ Piscine Pro</h1>", unsafe_allow_html=True)
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

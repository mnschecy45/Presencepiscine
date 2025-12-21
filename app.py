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
    
    # LOGIN
    password = st.sidebar.text_input("🔒 Code Manager", type="password")
    if password != MANAGER_PASSWORD:
        st.info("Mot de passe requis dans la barre latérale.")
        return

    # DONNÉES
    if df_all.empty:
        st.warning("Base de données vide.")
        return

    # Préparation
    df_work = df_all.copy()
    if "Date_dt" not in df_work.columns and "Date" in df_work.columns:
         df_work["Date_dt"] = pd.to_datetime(df_work["Date"], errors='coerce')
    
    # --- ONGLETS ---
    # J'ai renommé l'onglet 3 pour être plus clair
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 Dashboard", "🗓️ Planning", "🚨 Suivi Absences", "⚡ Actions", "⚙️ Config"])

    # ==========================
    # TAB 1 : DASHBOARD
    # ==========================
    with tab1:
        st.subheader("Vue d'ensemble")
        
        nb_total_lignes = len(df_work)
        nb_absences_total = len(df_work[df_work["Statut"] == "Absent"])
        
        # Calcul du taux de présence global
        taux = ((nb_total_lignes - nb_absences_total) / nb_total_lignes * 100) if nb_total_lignes > 0 else 0
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Enregistrements", nb_total_lignes)
        c2.metric("Absences cumulées", nb_absences_total)
        c3.metric("Taux Présence", f"{taux:.1f}%")
        # Nombre de clients différents ayant au moins 1 absence
        nb_clients_pb = df_work[df_work["Statut"] == "Absent"]["Nom"].nunique()
        c4.metric("Clients avec absences", nb_clients_pb)

        st.write("---")
        st.caption("Évolution des absences")
        daily_abs = df_work[df_work["Statut"] == "Absent"].groupby("Date_dt").size()
        st.bar_chart(daily_abs, height=200, color="#ff4b4b")

    # ==========================
    # TAB 5 : CONFIG (Seuils en NOMBRE D'ABSENCES)
    # ==========================
    with tab5:
        st.header("⚙️ Config Alertes")
        c_seuils, c_msg = st.columns([1, 1])
        
        with c_seuils:
            st.subheader("Paliers d'absences")
            st.info("Définissez au bout de combien d'absences on change de niveau.")
            
            # P1
            c1a, c1b = st.columns([1, 2])
            p1_val = c1a.number_input("P1 : Nb Absences", value=st.session_state.get("p1_val", 1), min_value=1)
            p1_label = c1b.text_input("Label P1", value=st.session_state.get("p1_label", "Mail de rappel"))
            
            # P2
            c2a, c2b = st.columns([1, 2])
            p2_val = c2a.number_input("P2 : Nb Absences", value=st.session_state.get("p2_val", 3), min_value=1)
            p2_label = c2b.text_input("Label P2", value=st.session_state.get("p2_label", "Appel téléphonique"))
            
            # P3
            c3a, c3b = st.columns([1, 2])
            p3_val = c3a.number_input("P3 : Nb Absences", value=st.session_state.get("p3_val", 5), min_value=1)
            p3_label = c3b.text_input("Label P3", value=st.session_state.get("p3_label", "Convocation"))
            
            if st.button("💾 Sauvegarder Seuils"):
                st.session_state["p1_val"] = p1_val; st.session_state["p1_label"] = p1_label
                st.session_state["p2_val"] = p2_val; st.session_state["p2_label"] = p2_label
                st.session_state["p3_val"] = p3_val; st.session_state["p3_label"] = p3_label
                st.success("Configuration enregistrée !")

        with c_msg:
            st.subheader("Message Type")
            default_msg = "Bonjour {prenom},\n\nSauf erreur de notre part, nous avons relevé les absences suivantes :\n{details}\n\nMerci de nous confirmer votre présence pour la prochaine séance.\n\nCordialement,\nL'équipe Piscine."
            tpl = st.text_area("Contenu", value=st.session_state.get("msg_tpl", default_msg), height=300)
            
            if st.button("💾 Sauvegarder Message"):
                st.session_state["msg_tpl"] = tpl
                st.success("Message enregistré !")

    # ==========================
    # TAB 3 : SUIVI ABSENCES (Logique corrigée : COMPTAGE)
    # ==========================
    with tab3:
        st.subheader("🚨 Suivi par nombre d'absences")
        
        # 1. On isole uniquement les lignes "Absent"
        df_absents_only = df_work[df_work["Statut"] == "Absent"]
        
        if not df_absents_only.empty:
            # 2. On compte combien de fois chaque nom apparait en "Absent"
            bilan_absences = df_absents_only["Nom"].value_counts().reset_index()
            bilan_absences.columns = ["Nom", "Total_Absences"]
            
            # 3. On récupère les seuils
            s1 = st.session_state.get("p1_val", 1)
            s2 = st.session_state.get("p2_val", 3)
            s3 = st.session_state.get("p3_val", 5)
            
            # 4. On attribue le niveau P1/P2/P3 selon le NOMBRE
            def get_niveau(nb):
                if nb >= s3: return f"🔴 P3 ({st.session_state.get('p3_label', 'Convocation')})"
                elif nb >= s2: return f"🟠 P2 ({st.session_state.get('p2_label', 'Appel')})"
                elif nb >= s1: return f"🟡 P1 ({st.session_state.get('p1_label', 'Mail')})"
                else: return "OK" # (Ne devrait pas arriver si on filtre > 0)

            bilan_absences["Niveau"] = bilan_absences["Total_Absences"].apply(get_niveau)
            
            # 5. Affichage trié par nombre d'absences (les pires en haut)
            st.dataframe(bilan_absences, use_container_width=True)
            
        else:
            st.success("Aucune absence enregistrée dans la base !")

    # ==========================
    # TAB 4 : ACTIONS (Génération message)
    # ==========================
    with tab4:
        st.subheader("⚡ Traitement des Absences")
        
        if 'bilan_absences' in locals() and not bilan_absences.empty:
            
            liste_clients = bilan_absences["Nom"].tolist()
            client_select = st.selectbox("Qui voulez-vous relancer ?", liste_clients)
            
            if client_select:
                info = bilan_absences[bilan_absences["Nom"] == client_select].iloc[0]
                nb = info["Total_Absences"]
                niv = info["Niveau"]
                
                st.info(f"**Client :** {client_select} | **Niveau :** {niv} | **Total Absences :** {nb}")
                
                # --- GÉNÉRATION DÉTAILS ---
                ses_absences = df_work[(df_work["Nom"] == client_select) & (df_work["Statut"] == "Absent")]
                # On trie pour avoir la plus récente en premier
                ses_absences = ses_absences.sort_values("Date_dt", ascending=False)
                
                lignes_details = []
                for _, row in ses_absences.iterrows():
                    # 1. NETTOYAGE DE LA DATE
                    if pd.notnull(row["Date_dt"]):
                        date_str = row["Date_dt"].strftime("%d/%m/%Y") # Donne 17/12/2025
                        # On essaie de récupérer l'heure depuis la date (ex: 17h30)
                        heure_str = row["Date_dt"].strftime("%Hh%M")
                    else:
                        date_str = "Date inconnue"
                        heure_str = ""

                    # 2. NETTOYAGE DU COURS
                    # Si la colonne Cours existe et n'est pas vide, on la prend. Sinon on met "Séance"
                    cours_brut = row.get("Cours")
                    if cours_brut and str(cours_brut) != "nan" and str(cours_brut) != "?":
                        cours_str = str(cours_brut)
                    else:
                        cours_str = "Séance" # Valeur par défaut si pas de nom de cours

                    # 3. CONSTRUCTION DE LA LIGNE PROPRE
                    # Résultat : "- Aquabike le 17/12/2025 à 18h30"
                    if heure_str and heure_str != "00h00":
                        ligne = f"- {cours_str} le {date_str} à {heure_str}"
                    else:
                        # Si pas d'heure précise, on met juste la date
                        ligne = f"- {cours_str} le {date_str}"
                        
                    lignes_details.append(ligne)
                
                txt_details = "\n".join(lignes_details)
                
                # --- INJECTION DANS LE MESSAGE ---
                tpl = st.session_state.get("msg_tpl", default_msg) 
                
                msg_final = tpl.replace("{prenom}", client_select).replace("{details}", txt_details)
                
                st.text_area("Message prêt à copier :", value=msg_final, height=250)
                
                if st.button("Marquer comme TRAITÉ"):
                    st.toast(f"Relance notée pour {client_select}", icon="✅")
        else:
            st.info("Tout le monde est présent, rien à faire !")

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

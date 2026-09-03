import json
import requests
import streamlit as st
from PIL import Image
import io
import google.generativeai as genai
from concurrent.futures import ThreadPoolExecutor
from fpdf import FPDF

st.set_page_config(page_title="MTG Commander Assistant", layout="wide")

st.title("MTG Commander Assistant")
st.subheader("Protótipo 0.9.4 - Scanner Sequencial Robusto")

# --- BUSCA DINÂMICA DE COMANDANTES NO SCRYFALL ---
@st.cache_data(ttl=3600)
def search_commanders_scryfall(query_term):
    if not query_term or len(query_term.strip()) < 2:
        return [
            "Atraxa, Praetors' Voice", "Krenko, Mob Boss", "Edgar Markov", 
            "Yuriko, the Tiger's Shadow", "Urza, Lord High Artificer", 
            "Lathril, Blade of the Elves", "The Ur-Dragon", "Muldrotha, the Gravetide",
            "Frodo, Sauron's Bane", "Shadowheart, Dark Justiciar", "Hazel of the Rootbloom",
            "Tymna the Weaver", "Kraum, Ludevic's Opus"
        ]

    headers = {"User-Agent": "MTGCommanderAssistant/1.0", "Accept": "application/json"}
    encoded_query = requests.utils.quote(f'is:commander name:"{query_term.strip()}"')
    url = f"https://api.scryfall.com/cards/search?q={encoded_query}&order=name"
    
    try:
        res = requests.get(url, headers=headers, timeout=4)
        if res.status_code == 200:
            data = res.json().get("data", [])
            names = [card.get("name") for card in data if not card.get("name", "").startswith("A-")]
            if names:
                return sorted(list(set(names)))
    except Exception:
        pass

    try:
        auto_url = f"https://api.scryfall.com/cards/autocomplete?q={requests.utils.quote(query_term.strip())}"
        res = requests.get(auto_url, headers=headers, timeout=3)
        if res.status_code == 200:
            names = res.json().get("data", [])
            return sorted([n for n in names if not n.startswith("A-")])
    except Exception:
        pass

    return []

def translate_type_line(type_line):
    if not type_line:
        return "Desconhecido"
    translations = {
        "Creature": "Criatura", "Legendary": "Lendário(a)", "Artifact": "Artefato",
        "Enchantment": "Encantamento", "Instant": "Mágica Instantânea", "Sorcery": "Feitiço",
        "Land": "Terreno", "Planeswalker": "Planeswalker", "Battle": "Batalha",
        "Saga": "Saga", "Equipment": "Equipamento", "Aura": "Aura",
        "Basic": "Básico", "Snow": "Neve", "Kindred": "Tribal", "Tribal": "Tribal"
    }
    res = type_line
    for eng, pt in translations.items():
        res = res.replace(eng, pt)
    return res

def call_gemini_api(api_key, prompt, image=None):
    genai.configure(api_key=api_key)
    
    fallback_models = [
        'gemini-2.5-flash',
        'gemini-2.0-flash',
        'gemini-1.5-flash',
        'gemini-1.5-flash-latest'
    ]
    
    last_error = None
    for model_name in fallback_models:
        try:
            model = genai.GenerativeModel(model_name)
            inputs = [prompt, image] if image is not None else [prompt]
            res = model.generate_content(inputs)
            if res and hasattr(res, 'text') and res.text:
                return res.text
        except Exception as e:
            last_error = e
            continue
            
    raise RuntimeError(f"Não foi possível obter resposta da API. Último erro: {last_error}")

def compress_image_for_api(pil_image, max_dim=1400):
    img = pil_image.copy()
    img.thumbnail((max_dim, max_dim))
    buffer = io.BytesIO()
    if img.mode != 'RGB':
        img = img.convert('RGB')
    img.save(buffer, format="JPEG", quality=85)
    buffer.seek(0)
    return Image.open(buffer)

@st.cache_data(ttl=3600)
def fetch_scryfall_card(card_name):
    if not card_name or not card_name.strip():
        return {"name": "", "found": False, "color_identity": [], "type_line": "", "image_url": ""}
    
    headers = {"User-Agent": "MTGCommanderAssistant/1.0", "Accept": "application/json"}
    encoded_name = requests.utils.quote(card_name.strip())
    url = f"https://api.scryfall.com/cards/named?exact={encoded_name}"
    
    try:
        response = requests.get(url, headers=headers, timeout=3)
        if response.status_code != 200:
            url = f"https://api.scryfall.com/cards/named?fuzzy={encoded_name}"
            response = requests.get(url, headers=headers, timeout=3)
            
        if response.status_code == 200:
            data = response.json()
            image_url = ""
            if "image_uris" in data:
                image_url = data["image_uris"].get("normal", "")
            elif "card_faces" in data and len(data["card_faces"]) > 0 and "image_uris" in data["card_faces"][0]:
                image_url = data["card_faces"][0]["image_uris"].get("normal", "")
                
            return {
                "name": data.get("name", card_name),
                "color_identity": data.get("color_identity", []),
                "type_line": data.get("type_line", ""),
                "oracle_text": data.get("oracle_text", ""),
                "image_url": image_url,
                "found": True
            }
    except Exception:
        pass
        
    return {"name": card_name, "found": False, "color_identity": [], "type_line": "", "image_url": ""}

def is_color_valid(card_colors, commander_colors):
    return set(card_colors).issubset(set(commander_colors))

@st.cache_data(ttl=3600)
def fetch_edhrec_full_metrics(commander_name):
    headers = {"User-Agent": "MTGCommanderAssistant/1.0"}
    slug = commander_name.lower().replace("'", "").replace(",", "").replace(" ", "-")
    url = f"https://json.edhrec.com/pages/commanders/{slug}.json"
    
    edh_db = {}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            container = data.get("container", {}).get("json_dict", {}).get("cardlists", [])
            for cardlist in container:
                header_category = cardlist.get("header", "Geral")
                for card in cardlist.get("cardviews", []):
                    c_name = card.get("name")
                    synergy_val = card.get("synergy", 0)
                    syn_pct = f"{int(synergy_val * 100):+d}%" if synergy_val else "0%"
                    label = card.get("label", "N/A")
                    
                    edh_db[c_name.lower()] = {
                        "name": c_name,
                        "synergy": syn_pct,
                        "synergy_raw": synergy_val,
                        "inclusion": label,
                        "category": header_category
                    }
    except Exception:
        pass
    return edh_db

def generate_pdf_report(title_text, content_text):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 10, "MTG Commander Assistant - Relatorio", ln=True, align="C")
    pdf.set_font("Helvetica", "I", 9)
    pdf.cell(0, 6, f"Foco: {title_text}", ln=True, align="C")
    pdf.ln(8)
    pdf.set_font("Helvetica", "", 10)
    
    clean_text = content_text.encode('latin-1', 'replace').decode('latin-1')
    
    for line in clean_text.split('\n'):
        line_clean = line.replace('#', '').replace('**', '').strip()
        if not line_clean:
            pdf.ln(3)
            continue
        if line.startswith("### "):
            pdf.ln(3)
            pdf.set_font("Helvetica", "B", 11)
            pdf.multi_cell(0, 6, line_clean.replace("### ", ""))
            pdf.set_font("Helvetica", "", 10)
        elif line.startswith("- ") or line.startswith("* "):
            pdf.multi_cell(0, 5, "  * " + line_clean[2:])
        else:
            pdf.multi_cell(0, 5, line_clean)
            
    return bytes(pdf.output())

# --- BARRA LATERAL ---
st.sidebar.header("Configurações e Comandante")
api_key_input = st.sidebar.text_input("Gemini API Key:", type="password")
api_key = api_key_input or st.secrets.get("GEMINI_API_KEY", "")

if not api_key:
    st.info("Insira sua Gemini API Key na barra lateral para continuar.")
    st.stop()

st.sidebar.success("API Ativa")
st.sidebar.markdown("---")
st.sidebar.subheader("Seleção de Comandante(s)")

mode_commanders = st.sidebar.radio("Modo de Comandante:", ["Comandante Único", "Parceiros / Dupla (2 Comandantes)"])

search_term_1 = st.sidebar.text_input("Pesquisar Comandante 1:", key="search_cmd_1")
filtered_1 = search_commanders_scryfall(search_term_1)
cmd_1_name = st.sidebar.selectbox("Comandante Principal:", options=filtered_1, index=0, key="sel_cmd_1") if filtered_1 else None

cmd_2_name = None
if mode_commanders == "Parceiros / Dupla (2 Comandantes)":
    search_term_2 = st.sidebar.text_input("Pesquisar Comandante 2:", key="search_cmd_2")
    filtered_2 = search_commanders_scryfall(search_term_2)
    cmd_2_name = st.sidebar.selectbox("Segundo Comandante:", options=filtered_2, index=0, key="sel_cmd_2") if filtered_2 else None

if cmd_1_name:
    c1_data = fetch_scryfall_card(cmd_1_name)
    combined_colors = set(c1_data.get("color_identity", []))
    display_name = c1_data['name']
    images_to_show = [c1_data['image_url']] if c1_data['image_url'] else []
    
    if cmd_2_name:
        c2_data = fetch_scryfall_card(cmd_2_name)
        combined_colors.update(c2_data.get("color_identity", []))
        display_name += f" & {c2_data['name']}"
        if c2_data['image_url']:
            images_to_show.append(c2_data['image_url'])
            
    final_color_list = sorted(list(combined_colors))
    st.session_state['commander_data'] = {"name": display_name, "color_identity": final_color_list, "found": True}
    
    st.sidebar.markdown("---")
    st.sidebar.subheader(f"Deck: {display_name}")
    st.sidebar.caption(f"Cores: {', '.join(final_color_list) if final_color_list else 'Incolor'}")
    for img_url in images_to_show:
        st.sidebar.image(img_url, use_container_width=True)

# --- UPLOAD MULTI-IMAGEM SEQUENCIAL (ROBUSTO) ---
st.write("### Leitura de Coleção e Fichários em Lote")
uploaded_files = st.file_uploader("Envie as fotos das páginas do fichário:", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True)

if uploaded_files:
    st.write(f"**{len(uploaded_files)} foto(s) carregada(s).**")
    
    if st.button("Escanear Fotos", type="primary"):
        all_cards_map = {}
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for idx, file in enumerate(uploaded_files):
            status_text.text(f"Analisando imagem {idx+1} de {len(uploaded_files)} ({file.name})...")
            try:
                raw_img = Image.open(file)
                optimized_img = compress_image_for_api(raw_img)
                prompt = """
                Analise esta imagem de uma página de fichário de Magic: The Gathering.
                Identifique todas as cartas visíveis na foto e seus respectivos nomes oficiais em inglês.
                Retorne a resposta EXATAMENTE no formato JSON de um array de objetos, sem nenhum texto adicional fora do JSON:
                [
                  {"card_name": "Nome da Carta", "qty": 1}
                ]
                """
                raw_text = call_gemini_api(api_key, prompt, optimized_img)
                
                clean_json_str = raw_text.strip()
                if "```" in clean_json_str:
                    parts = clean_json_str.split("```")
                    for part in parts:
                        cp = part.strip()
                        if cp.startswith("json"): 
                            cp = cp[4:].strip()
                        if cp.startswith("[") and cp.endswith("]"): 
                            clean_json_str = cp
                            break
                
                cards_list = json.loads(clean_json_str)
                for item in cards_list:
                    name = item.get("card_name", "").strip()
                    qty = int(item.get("qty", 1))
                    if name:
                        key = name.lower()
                        if key in all_cards_map:
                            all_cards_map[key]["qty"] += qty
                        else:
                            all_cards_map[key] = {"card_name": name, "qty": qty}
            except Exception as e:
                print(f"Erro ao processar imagem {file.name}: {e}")
            
            progress_bar.progress((idx + 1) / len(uploaded_files))
            
        status_text.empty()
        compiled_list = list(all_cards_map.values())
        st.session_state['detected_cards'] = compiled_list
        st.success(f"Varredura concluída com sucesso! {len(compiled_list)} carta(s) única(s) identificadas.")

# --- VALIDAÇÃO EM PARALELO ---
def _process_single_card(item, cmd_colors, edhrec_db):
    scry = fetch_scryfall_card(item['card_name'])
    if scry['found']:
        valid = is_color_valid(scry['color_identity'], cmd_colors)
        edh_info = edhrec_db.get(scry['name'].lower(), {})
        raw_syn = edh_info.get("synergy_raw", 0)
        has_edh_data = edh_info.get("inclusion") is not None
        
        card_dict = {
            "Carta": scry['name'],
            "Qtd": item['qty'],
            "Tipo": translate_type_line(scry['type_line']),
            "Valida": "Sim" if valid else "Fora da Cor",
            "Inclusão EDHREC": edh_info.get("inclusion", "Fora do Top EDHREC"),
            "Sinergia EDHREC": edh_info.get("synergy", "0%"),
            "Categoria EDHREC": edh_info.get("category", "Geral/Outros"),
            "_oracle_text": scry['oracle_text']
        }
        return card_dict, (valid and (has_edh_data or raw_syn > 0))
    return None, False

if 'detected_cards' in st.session_state and st.session_state['detected_cards']:
    st.markdown("---")
    st.write("### Triagem da Coleção vs Comandante")
    
    if st.button("Validar Coleção Instantaneamente"):
        with st.spinner("Cruzando dados no Scryfall e EDHREC em paralelo..."):
            cmd_data = st.session_state.get('commander_data', {})
            cmd_name = cmd_data.get('name', '').split(" & ")[0]
            cmd_colors = cmd_data.get('color_identity', [])
            
            edhrec_db = fetch_edhrec_full_metrics(cmd_name)
            playable_cards, junk_cards = [], []
            
            with ThreadPoolExecutor(max_workers=12) as executor:
                futures = [executor.submit(_process_single_card, item, cmd_colors, edhrec_db) for item in st.session_state['detected_cards']]
                for future in futures:
                    card_dict, is_playable = future.result()
                    if card_dict:
                        if is_playable: playable_cards.append(card_dict)
                        else: junk_cards.append(card_dict)
            
            st.session_state['playable_cards'] = playable_cards
            st.session_state['junk_cards'] = junk_cards

    if 'playable_cards' in st.session_state:
        tab1, tab2 = st.tabs([f"Aproveitáveis ({len(st.session_state['playable_cards'])} cartas)", f"Descarte ({len(st.session_state['junk_cards'])} cartas)"])
        
        def clean_display_list(card_list):
            return [{k: v for k, v in c.items() if not k.startswith("_")} for c in card_list]

        with tab1:
            st.dataframe(clean_display_list(st.session_state['playable_cards']), use_container_width=True)
        with tab2:
            st.dataframe(clean_display_list(st.session_state['junk_cards']), use_container_width=True)
        
        st.markdown("---")
        st.write("### Análise Cirúrgica de Sinergias")
        
        if st.button("Gerar Matriz de Sinergias Rápida", type="primary"):
            with st.spinner("Gerando matriz otimizada..."):
                try:
                    cmd_name = st.session_state.get('commander_data', {}).get('name', 'Comandante')
                    valid_playables = [c for c in st.session_state['playable_cards'] if c['Valida'] == "Sim"]
                    
                    cards_data_prompt = "\n".join([f"- {c['Carta']} ({c['Tipo']}) | Sinergia: {c['Sinergia EDHREC']}" for c in valid_playables[:40]])
                    
                    prompt = f"""
                    Analise de forma OBJETIVA e DIRETA para o comandante {cmd_name} com base nestas cartas:
                    {cards_data_prompt}
                    Gere estritamente duas seções:
                    ### Cartas Recomendadas da Coleção
                    | Carta | Tipo | Categoria | Inclusão (%) | Sinergia (%) |
                    ### Matriz de Sinergias Cruzadas
                    - **[Carta A] + [Carta B]**: [Explicação de até 10 palavras].
                    """
                    res_text = call_gemini_api(api_key, prompt)
                    st.session_state['last_synergy_analysis'] = res_text
                    st.markdown(res_text)
                except Exception as e:
                    st.error(f"Erro: {e}")

        if 'last_synergy_analysis' in st.session_state:
            pdf_bytes = generate_pdf_report("Analise de Sinergias Cruzadas", st.session_state['last_synergy_analysis'])
            st.download_button(label="📥 Baixar Relatório (PDF)", data=pdf_bytes, file_name="mtg_sinergias.pdf", mime="application/pdf")

        # --- UPGRADES ---
        st.markdown("---")
        st.write("### Módulo de Upgrade")
        user_decklist = st.text_area("Cole sua lista de deck:", height=150)
        
        if st.button("Analisar Upgrades Rápidos", type="primary"):
            if user_decklist.strip():
                with st.spinner("Cruzando deck com fichário..."):
                    try:
                        cmd_name = st.session_state.get('commander_data', {}).get('name', 'Comandante')
                        valid_playables = [c for c in st.session_state['playable_cards'] if c['Valida'] == "Sim"]
                        binder_summary = "\n".join([f"- {c['Carta']} | Sinergia: {c['Sinergia EDHREC']}" for c in valid_playables])
                        
                        prompt = f"""
                        Compare o deck e o fichário para {cmd_name}.
                        DECK: {user_decklist.strip()}
                        FICHÁRIO: {binder_summary}
                        Gere APENAS:
                        ### Sugestões de Trocas Diretas
                        - **Entra:** [Carta] | **Sai:** [Carta] | **Motivo:** [Breve]
                        """
                        upgrade_res = call_gemini_api(api_key, prompt)
                        st.session_state['last_upgrade_analysis'] = upgrade_res
                        st.markdown(upgrade_res)
                    except Exception as e:
                        st.error(f"Erro: {e}")

        if 'last_upgrade_analysis' in st.session_state:
            pdf_upgrade_bytes = generate_pdf_report("Relatorio de Upgrade", st.session_state['last_upgrade_analysis'])
            st.download_button(label="📥 Baixar Relatório de Upgrades (PDF)", data=pdf_upgrade_bytes, file_name="mtg_upgrades.pdf", mime="application/pdf")

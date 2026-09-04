import json
import sqlite3
import time
import io
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import streamlit as st
from PIL import Image
import google.generativeai as genai
from concurrent.futures import ThreadPoolExecutor

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Shaper of Commander",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- CARREGAMENTO INVISÍVEL DA CHAVE ---
api_key = st.secrets.get("GEMINI_API_KEY", "")

if not api_key:
    st.error("Erro de configuração: A chave GEMINI_API_KEY não foi encontrada nos Secrets do servidor.")
    st.stop()

# --- ESTILIZAÇÃO VISUAL CUSTOMIZADA (IMAGEM DE FUNDO MTG / TEMA DARK RESPONSIVO) ---
st.markdown("""
<style>
    /* 1. Ocultar rodapé e marcas nativas mantendo o menu mobile utilizável */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* 2. Fundo geral com imagem temática de Magic: The Gathering e camada escura */
    .stApp {
        background-image: linear-gradient(rgba(11, 15, 25, 0.88), rgba(11, 15, 25, 0.88)), url("https://cards.scryfall.io/art_crop/front/b/d/bd8fa327-dd41-4737-8f19-2cf5eb1f7cdd.jpg");
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
        color: #e2e8f0;
        font-family: 'Inter', system-ui, -apple-system, sans-serif;
    }
    
    /* 3. Títulos e Subtítulos em destaque */
    h1, h2, h3 {
        color: #f8fafc !important;
        font-weight: 700 !important;
        letter-spacing: -0.02em;
    }
    
    /* 4. Estilo dos Cartões de Etapa (Wizard) */
    .step-card {
        background-color: rgba(17, 24, 39, 0.85);
        border: 1px solid #1f2937;
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 24px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.4);
        backdrop-filter: blur(4px);
    }
    
    /* 5. Botões modernos em azul/roxo degradê */
    .stButton>button {
        background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%) !important;
        color: #ffffff !important;
        border: none !important;
        border-radius: 8px !important;
        padding: 0.65rem 1.2rem !important;
        font-weight: 600 !important;
        transition: all 0.2s ease-in-out !important;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3) !important;
        width: 100%;
    }
    .stButton>button:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 6px 15px rgba(99, 102, 241, 0.4) !important;
    }
    
    /* 6. Abas estilizadas (Tabs) */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: rgba(30, 41, 59, 0.85);
        padding: 6px;
        border-radius: 10px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 6px;
        color: #94a3b8;
        font-weight: 600;
    }
    .stTabs [aria-selected="true"] {
        background-color: #3b82f6 !important;
        color: #ffffff !important;
    }
    
    /* 7. Caixas de texto, inputs e uploaders */
    .stTextArea textarea, .stTextInput input {
        background-color: rgba(15, 23, 42, 0.85) !important;
        color: #f8fafc !important;
        border: 1px solid #334155 !important;
        border-radius: 8px !important;
    }
    
    /* 8. Estilo de Dataframes e tabelas */
    [data-testid="stDataFrame"] {
        border: 1px solid #1f2937;
        border-radius: 8px;
        overflow: hidden;
        background-color: rgba(15, 23, 42, 0.8);
    }
</style>
""", unsafe_allow_html=True)

# --- BANCO DE DADOS SQLITE PARA CACHE PERSISTENTE ---
DB_NAME = "mtg_cache.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS scryfall_cache (
            query_key TEXT PRIMARY KEY,
            json_data TEXT,
            timestamp REAL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS edhrec_cache (
            commander_slug TEXT PRIMARY KEY,
            json_data TEXT,
            timestamp REAL
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_cached_data(table, key):
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute(f"SELECT json_data, timestamp FROM {table} WHERE query_key=?" if table == "scryfall_cache" else f"SELECT json_data, timestamp FROM {table} WHERE commander_slug=?", (key,))
        row = c.fetchone()
        conn.close()
        if row:
            if time.time() - row[1] < 604800: # Cache válido por 7 dias
                return json.loads(row[0])
    except Exception:
        pass
    return None

def set_cached_data(table, key, data):
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        json_str = json.dumps(data)
        now = time.time()
        if table == "scryfall_cache":
            c.execute("INSERT OR REPLACE INTO scryfall_cache (query_key, json_data, timestamp) VALUES (?, ?, ?)", (key, json_str, now))
        else:
            c.execute("INSERT OR REPLACE INTO edhrec_cache (commander_slug, json_data, timestamp) VALUES (?, ?, ?)", (key, json_str, now))
        conn.commit()
        conn.close()
    except Exception:
        pass

# --- SESSÃO HTTP COM RATE LIMITING E RETRIES AUTOMÁTICOS ---
def get_http_session():
    session = requests.Session()
    retries = Retry(
        total=4,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

HTTP = get_http_session()

# --- BUSCA DE COMANDANTES NO SCRYFALL ---
def search_commanders_scryfall(query_term):
    if not query_term or len(query_term.strip()) < 2:
        return [
            "Hazezon, Shaper of Sand", "Atraxa, Praetors' Voice", "Krenko, Mob Boss", "Edgar Markov", 
            "Yuriko, the Tiger's Shadow", "Urza, Lord High Artificer", 
            "Lathril, Blade of the Elves", "The Ur-Dragon", "Muldrotha, the Gravetide",
            "Frodo, Sauron's Bane", "Shadowheart, Dark Justiciar", "Hazel of the Rootbloom"
        ]

    cache_key = f"search_{query_term.strip().lower()}"
    cached = get_cached_data("scryfall_cache", cache_key)
    if cached:
        return cached

    headers = {"User-Agent": "MTGCommanderAssistant/1.0", "Accept": "application/json"}
    encoded_query = requests.utils.quote(f'lang:any (is:commander or type:background) name:"{query_term.strip()}"')
    url = f"https://api.scryfall.com/cards/search?q={encoded_query}&order=name"
    
    try:
        time.sleep(0.05)
        res = HTTP.get(url, headers=headers, timeout=6)
        if res.status_code == 200:
            data = res.json().get("data", [])
            names = [card.get("name") for card in data if not card.get("name", "").startswith("A-")]
            if names:
                unique_names = sorted(list(set(names)))
                set_cached_data("scryfall_cache", cache_key, unique_names)
                return unique_names
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

# --- INTEGRAÇÃO GEMINI API (DETERMINÍSTICA / TEMP = 0.0) ---
def call_gemini_api(api_key, prompt, image=None):
    genai.configure(api_key=api_key)
    
    generation_config = genai.types.GenerationConfig(
        temperature=0.0
    )
    
    valid_models = []
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                valid_models.append(m.name)
    except Exception:
        pass
    
    fallback_models = ['gemini-1.5-flash', 'gemini-1.5-flash-latest', 'gemini-2.0-flash', 'gemini-1.5-pro']
    flash_dynamic = [m for m in valid_models if 'flash' in m.lower()]
    other_dynamic = [m for m in valid_models if m not in flash_dynamic]
    candidates = flash_dynamic + other_dynamic + [m for m in fallback_models if m not in valid_models]
    
    last_error = None
    for model_name in candidates:
        try:
            model = genai.GenerativeModel(model_name, generation_config=generation_config)
            inputs = [prompt, image] if image is not None else [prompt]
            res = model.generate_content(inputs)
            if res and hasattr(res, 'text') and res.text:
                return res.text
        except Exception as e:
            last_error = e
            continue
            
    raise RuntimeError(f"Erro na API Gemini: {last_error}")

def compress_image_for_api(pil_image, max_dim=1600):
    img = pil_image.copy()
    img.thumbnail((max_dim, max_dim))
    buffer = io.BytesIO()
    if img.mode != 'RGB':
        img = img.convert('RGB')
    img.save(buffer, format="JPEG", quality=85)
    buffer.seek(0)
    return Image.open(buffer)

def fetch_scryfall_card(card_name):
    if not card_name or not card_name.strip():
        return {"name": "", "found": False, "color_identity": [], "type_line": "", "image_url": "", "oracle_text": "", "has_partner": False}
    
    cache_key = f"card_{card_name.strip().lower()}"
    cached = get_cached_data("scryfall_cache", cache_key)
    if cached:
        return cached

    headers = {"User-Agent": "MTGCommanderAssistant/1.0", "Accept": "application/json"}
    encoded_name = requests.utils.quote(card_name.strip())
    url = f"https://api.scryfall.com/cards/named?exact={encoded_name}"
    
    try:
        time.sleep(0.05)
        response = HTTP.get(url, headers=headers, timeout=5)
        if response.status_code != 200:
            url = f"https://api.scryfall.com/cards/named?fuzzy={encoded_name}"
            response = HTTP.get(url, headers=headers, timeout=5)
            
        if response.status_code != 200:
            search_url = f"https://api.scryfall.com/cards/search?q=lang:any+\"{encoded_name}\""
            search_res = HTTP.get(search_url, headers=headers, timeout=5)
            if search_res.status_code == 200:
                response = search_res

        if response.status_code == 200:
            data = response.json()
            if "data" in data and isinstance(data["data"], list) and len(data["data"]) > 0:
                data = data["data"][0]
                
            image_url = ""
            if "image_uris" in data:
                image_url = data["image_uris"].get("normal", "")
            elif "card_faces" in data and len(data["card_faces"]) > 0 and "image_uris" in data["card_faces"][0]:
                image_url = data["card_faces"][0]["image_uris"].get("normal", "")
            
            oracle_text = data.get("oracle_text", "")
            type_line = data.get("type_line", "")
            keywords = [k.lower() for k in data.get("keywords", [])]
            text_lower = oracle_text.lower()
            
            partner_keywords = ["partner", "choose a background", "friends forever", "doctor's companion"]
            has_partner = any(kw in keywords for kw in partner_keywords) or any(term in text_lower for term in partner_keywords)
            if "background" in type_line.lower():
                has_partner = True
                
            result = {
                "name": data.get("name", card_name),
                "color_identity": data.get("color_identity", []),
                "type_line": type_line,
                "oracle_text": oracle_text,
                "image_url": image_url,
                "found": True,
                "has_partner": has_partner
            }
            set_cached_data("scryfall_cache", cache_key, result)
            return result
    except Exception:
        pass
        
    return {"name": card_name, "found": False, "color_identity": [], "type_line": "", "image_url": "", "oracle_text": "", "has_partner": False}

def is_color_valid(card_colors, commander_colors):
    return set(card_colors).issubset(set(commander_colors))

def fetch_edhrec_full_metrics(commander_name):
    headers = {"User-Agent": "MTGCommanderAssistant/1.0"}
    slug = commander_name.lower().replace("'", "").replace(",", "").replace(" ", "-")
    
    cached = get_cached_data("edhrec_cache", slug)
    if cached:
        return cached

    url = f"https://json.edhrec.com/pages/commanders/{slug}.json"
    edh_db = {}
    try:
        res = HTTP.get(url, headers=headers, timeout=10)
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
            set_cached_data("edhrec_cache", slug, edh_db)
    except Exception:
        pass
    return edh_db

# --- CABEÇALHO PRINCIPAL ---
st.title("SHAPER OF COMMANDER DECK")
st.markdown("---")

# ==========================================
# PASSO 1: SELEÇÃO DO COMANDANTE
# ==========================================
st.subheader("PASSO 1: Seleção do Comandante")

col_cmd1, col_cmd2 = st.columns([2, 1])

with col_cmd1:
    search_term_1 = st.text_input("Digite o nome do Comandante:", placeholder="Ex: Hazezon, Aloy, Hamza", key="search_cmd_1")
    filtered_1 = search_commanders_scryfall(search_term_1)
    cmd_1_name = st.selectbox("Selecione na lista:", options=filtered_1, index=0, key="sel_cmd_1") if filtered_1 else None

    cmd_2_name = None
    if cmd_1_name:
        c1_data = fetch_scryfall_card(cmd_1_name)
        combined_colors = set(c1_data.get("color_identity", []))
        display_name = c1_data['name']
        images_to_show = [c1_data['image_url']] if c1_data['image_url'] else []
        
        if c1_data.get("has_partner", False):
            st.info("Este comandante aceita Parceiro/Background")
            search_term_2 = st.text_input("Digite o nome do Parceiro/Background:", placeholder="Ex: Samwise, Haunted One", key="search_cmd_2")
            filtered_2 = search_commanders_scryfall(search_term_2)
            cmd_2_name = st.selectbox("Selecione na lista:", options=filtered_2, index=0, key="sel_cmd_2") if filtered_2 else None

            if cmd_2_name:
                c2_data = fetch_scryfall_card(cmd_2_name)
                combined_colors.update(c2_data.get("color_identity", []))
                display_name += f" & {c2_data['name']}"
                if c2_data['image_url']:
                    images_to_show.append(c2_data['image_url'])
                    
        final_color_list = sorted(list(combined_colors))
        st.session_state['commander_data'] = {"name": display_name, "color_identity": final_color_list, "found": True}

with col_cmd2:
    if cmd_1_name:
        st.markdown(f"**Deck:** `{display_name}`")
        st.caption(f"Identidade de Cores: **{', '.join(final_color_list) if final_color_list else 'Incolor'}")
        img_cols = st.columns(len(images_to_show))
        for idx, img_url in enumerate(images_to_show):
            with img_cols[idx]:
                st.image(img_url, use_container_width=True)

st.markdown("---")

# ==========================================
# PASSO 2: ESCANEAMENTO E GERENCIAMENTO DO FICHÁRIO
# ==========================================
st.subheader("PASSO 2: Listagem das Cartas")

if 'detected_cards' not in st.session_state:
    st.session_state['detected_cards'] = []

uploaded_files = st.file_uploader("Envie imagens das cartas ou de páginas inteiras do fichário em boa qualidade:", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True)

col_scan1, col_scan2 = st.columns([2, 1])

with col_scan1:
    if uploaded_files:
        if st.button("Processar Imagens", type="primary"):
            all_cards_map = {c['card_name'].lower(): c for c in st.session_state['detected_cards']}
            progress_bar = st.progress(0)
            status_text = st.empty()
            failed_images = []
            
            for idx, file in enumerate(uploaded_files):
                status_text.text(f"Analisando imagem {idx+1} de {len(uploaded_files)} ({file.name})...")
                try:
                    raw_img = Image.open(file)
                    optimized_img = compress_image_for_api(raw_img)
                    prompt = """
                    Analise a imagem enviada (página de fichário de MTG).
                    Converta/Traduza o nome de cada carta para o NOME OFICIAL EM INGLÊS.
                    Responda APENAS com um array JSON válido: [{"card_name": "Sol Ring", "qty": 1}]
                    """
                    raw_text = call_gemini_api(api_key, prompt, optimized_img)
                    
                    backticks = "\x60\x60\x60"
                    if backticks in raw_text:
                        parts = raw_text.split(backticks)
                        for part in parts:
                            clean = part.strip()
                            if clean.startswith("json"): clean = clean[4:].strip()
                            if clean.startswith("["): raw_text = clean; break
                    
                    cards_list = json.loads(raw_text)
                    for item in cards_list:
                        name = item.get("card_name", "").strip()
                        qty = int(item.get("qty", 1))
                        if name:
                            key = name.lower()
                            if key in all_cards_map: all_cards_map[key]["qty"] += qty
                            else: all_cards_map[key] = {"card_name": name, "qty": qty}
                except Exception:
                    failed_images.append(file.name)
                
                progress_bar.progress((idx + 1) / len(uploaded_files))
                
            status_text.empty()
            st.session_state['detected_cards'] = list(all_cards_map.values())
            st.session_state.pop('playable_cards', None)
            if failed_images: st.warning(f"{len(failed_images)} imagem(ns) com falha.")
            st.success("Cartas identificadas com sucesso!")

with col_scan2:
    total_cards = sum([c['qty'] for c in st.session_state['detected_cards']])
    st.metric("Total", f"{total_cards} carta(s)")
    if st.session_state['detected_cards']:
        if st.button("RESETAR LISTAGEM"):
            st.session_state['detected_cards'] = []
            st.session_state.pop('playable_cards', None)
            st.session_state.pop('junk_cards', None)
            st.rerun()

st.markdown("---")

# ==========================================
# PASSO 3: DECKLIST ATUAL (OPCIONAL)
# ==========================================
st.subheader("OPCIONAL: Decklist Existente")
pasted_decklist = st.text_area(
    "Cole a lista do seu deck montado para buscar trocas e upgrades:",
    height=120,
    placeholder="1 Sol Ring\n1 Command Tower\n1 Rhystic Study...",
    key="pasted_decklist_input"
)

st.markdown("---")

# ==========================================
# PASSO 4: CENTRAL DE ANÁLISE E GALERIA
# ==========================================
st.subheader("CENTRAL DE ANÁLISE E UPGRADES")

def _process_single_card(item, cmd_colors, edhrec_db):
    scry = fetch_scryfall_card(item['card_name'])
    if scry['found']:
        valid = is_color_valid(scry['color_identity'], cmd_colors)
        edh_info = edhrec_db.get(scry['name'].lower(), {})
        raw_syn = edh_info.get("synergy_raw", 0)
        has_edh_data = edh_info.get("inclusion") is not None
        
        card_dict = {
            "Imagem": scry['image_url'],
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

if st.session_state['detected_cards']:
    if st.button("Analisar Sinergias para o Comandante selecionado", type="primary"):
        with st.spinner("Cruzando fichário com dados do EDHREC e regras do Comandante..."):
            cmd_data = st.session_state.get('commander_data', {})
            cmd_name = cmd_data.get('name', '').split(" & ")[0]
            cmd_colors = cmd_data.get('color_identity', [])
            
            edhrec_db = fetch_edhrec_full_metrics(cmd_name)
            playable_cards, junk_cards = [], []
            
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = [executor.submit(_process_single_card, item, cmd_colors, edhrec_db) for item in st.session_state['detected_cards']]
                for future in futures:
                    card_dict, is_playable = future.result()
                    if card_dict:
                        if is_playable: playable_cards.append(card_dict)
                        else: junk_cards.append(card_dict)
            
            st.session_state['playable_cards'] = playable_cards
            st.session_state['junk_cards'] = junk_cards

    if 'playable_cards' in st.session_state:
        tab1, tab2, tab3, tab4 = st.tabs([
            f"Aqui é Gameplay ({len(st.session_state['playable_cards'])})",
            f"Galeria",
            f"Deixa de Fora ({len(st.session_state['junk_cards'])})",
            f"Raio-X e Upgrades"
        ])

        column_config_spec = {
            "Imagem": st.column_config.ImageColumn("Arte", width="small"),
            "Carta": st.column_config.TextColumn("Nome da Carta"),
            "Qtd": st.column_config.NumberColumn("Qtd", width="small"),
            "Valida": st.column_config.TextColumn("Cor"),
            "Sinergia EDHREC": st.column_config.TextColumn("Sinergia"),
            "Inclusão EDHREC": st.column_config.TextColumn("Presença"),
        }

        clean_list = lambda l: [{k: v for k, v in c.items() if not k.startswith("_")} for c in l]

        with tab1:
            st.dataframe(
                clean_list(st.session_state['playable_cards']),
                column_config=column_config_spec,
                use_container_width=True,
                hide_index=True
            )

        with tab2:
            st.write("### Cartas Recomendadas do Fichário")
            playables = st.session_state['playable_cards']
            if playables:
                cols_per_row = 4
                for i in range(0, len(playables), cols_per_row):
                    row_cards = playables[i:i+cols_per_row]
                    cols = st.columns(cols_per_row)
                    for idx, card in enumerate(row_cards):
                        with cols[idx]:
                            if card['Imagem']:
                                st.image(card['Imagem'], use_container_width=True)
                            st.caption(f"**\n\nSinergia: `{card['Sinergia EDHREC']}`")
            else:
                st.info("Nenhuma carta com sinergia direta encontrada.")

        with tab3:
            st.dataframe(
                clean_list(st.session_state['junk_cards']),
                column_config=column_config_spec,
                use_container_width=True,
                hide_index=True
            )

        with tab4:
            st.write("### Análise Lógica Determinística")
            
            if st.button("Gerar Relatório Completo de Sinergias"):
                with st.spinner("Analisando interações no nível de texto das cartas..."):
                    try:
                        cmd_name = st.session_state.get('commander_data', {}).get('name', 'Comandante')
                        valid_playables = [c for c in st.session_state['playable_cards'] if c['Valida'] == "Sim"]
                        
                        fichario_prompt = "\n".join([f"- {c['Carta']} ({c['Tipo']}) | Sinergia EDH: {c['Sinergia EDHREC']} | Texto: {c.get('_oracle_text', '')[:80]}" for c in valid_playables])
                        
                        prompt = f"""
                        Você é um especialista em MTG Commander.
                        Análise determinística e cirúrgica para o Comandante: {cmd_name}

                        CARTAS RECOMENDADAS DO FICHÁRIO:
                        {fichario_prompt}

                        DECKLIST ATUAL DO JOGADOR:
                        {pasted_decklist.strip() if pasted_decklist else 'Nenhuma decklist informada.'}

                        Responda em Markdown estruturado:

                        ### 1. Sinergias Cruzadas (Cartas Enviadas)
                        - **[Carta A] + [Carta B]**: Explicar a sinergia direta em no máximo 15 palavras.

                        ### 2. Sugestões de Upgrades (Para Deck Existente)
                        - **Entra (Fichário): [Nome]** <--- **Sai (Deck Actual): [Nome]**: Motivo técnico direto.
                        """
                        
                        res_text = call_gemini_api(api_key, prompt)
                        st.markdown(res_text)
                    except Exception as e:
                        st.error(f"Erro na geração do relatório: {e}")
else:
    st.info("Envie e valide as cartas para iniciar as análises.")

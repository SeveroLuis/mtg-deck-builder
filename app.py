import json
import requests
import streamlit as st
from PIL import Image
import io
import google.generativeai as genai
from concurrent.futures import ThreadPoolExecutor

st.set_page_config(page_title="MTG Commander Assistant", layout="wide")

st.title("MTG Commander Assistant")
st.subheader("Protótipo 0.9.3 - Correção de String Literal")

# --- BUSCA DINÂMICA DE COMANDANTES NO SCRYFALL ---
@st.cache_data(ttl=3600)
def search_commanders_scryfall(query_term):
    """Busca em tempo real qualquer comandante no Scryfall que contenha o termo digitado."""
    if not query_term or len(query_term.strip()) < 2:
        return [
            "Atraxa, Praetors' Voice", "Krenko, Mob Boss", "Edgar Markov", 
            "Yuriko, the Tiger's Shadow", "Urza, Lord High Artificer", 
            "Lathril, Blade of the Elves", "The Ur-Dragon", "Muldrotha, the Gravetide",
            "Frodo, Sauron's Bane", "Shadowheart, Dark Justiciar", "Hazel of the Rootbloom",
            "Tymna the Weaver", "Kraum, Ludevic's Opus"
        ]

    headers = {
        "User-Agent": "MTGCommanderAssistant/1.0 ([https://github.com](https://github.com))",
        "Accept": "application/json"
    }
    
    encoded_query = requests.utils.quote(f'is:commander name:"{query_term.strip()}"')
    url = f"[https://api.scryfall.com/cards/search?q=](https://api.scryfall.com/cards/search?q=){encoded_query}&order=name"
    
    try:
        res = requests.get(url, headers=headers, timeout=6)
        if res.status_code == 200:
            data = res.json().get("data", [])
            names = [card.get("name") for card in data if not card.get("name", "").startswith("A-")]
            if names:
                return sorted(list(set(names)))
    except Exception:
        pass

    try:
        auto_url = f"[https://api.scryfall.com/cards/autocomplete?q=](https://api.scryfall.com/cards/autocomplete?q=){requests.utils.quote(query_term.strip())}"
        res = requests.get(auto_url, headers=headers, timeout=5)
        if res.status_code == 200:
            names = res.json().get("data", [])
            return sorted([n for n in names if not n.startswith("A-")])
    except Exception:
        pass

    return []

# --- TRADUÇÃO E SIMPLIFICAÇÃO DE TIPOS DE CARTAS ---
def translate_type_line(type_line):
    """Traduz e formata a linha de tipo das cartas para o português."""
    if not type_line:
        return "Desconhecido"
    
    translations = {
        "Creature": "Criatura",
        "Legendary": "Lendário(a)",
        "Artifact": "Artefato",
        "Enchantment": "Encantamento",
        "Instant": "Mágica Instantânea",
        "Sorcery": "Feitiço",
        "Land": "Terreno",
        "Planeswalker": "Planeswalker",
        "Battle": "Batalha",
        "Saga": "Saga",
        "Equipment": "Equipamento",
        "Aura": "Aura",
        "Basic": "Básico",
        "Snow": "Neve",
        "Kindred": "Tribal",
        "Tribal": "Tribal"
    }
    
    res = type_line
    for eng, pt in translations.items():
        res = res.replace(eng, pt)
    return res

# --- FUNÇÃO ROBUSTA DE CHAMADA À API GEMINI ---
def call_gemini_api(api_key, prompt, image=None):
    """Consulta dinamicamente os modelos disponíveis na API Key e executa a chamada com fallback automático."""
    genai.configure(api_key=api_key)
    
    valid_models = []
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                valid_models.append(m.name)
    except Exception:
        pass
    
    fallback_models = [
        'gemini-1.5-flash',
        'gemini-1.5-flash-latest',
        'gemini-2.0-flash',
        'gemini-2.5-flash',
        'gemini-1.5-pro',
        'gemini-1.5-pro-latest'
    ]
    
    flash_dynamic = [m for m in valid_models if 'flash' in m.lower()]
    other_dynamic = [m for m in valid_models if m not in flash_dynamic]
    
    candidates = flash_dynamic + other_dynamic + [m for m in fallback_models if m not in valid_models]
    
    last_error = None
    for model_name in candidates:
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

# --- OTIMIZAÇÃO DE IMAGEM PARA LOTES GRANDES ---
def compress_image_for_api(pil_image, max_dim=1600):
    """Redimensiona e otimiza a imagem para acelerar o envio na API e evitar timeouts."""
    img = pil_image.copy()
    img.thumbnail((max_dim, max_dim))
    buffer = io.BytesIO()
    if img.mode != 'RGB':
        img = img.convert('RGB')
    img.save(buffer, format="JPEG", quality=85)
    buffer.seek(0)
    return Image.open(buffer)

# --- FUNÇÕES AUXILIARES SCRYFALL & EDHREC ---
@st.cache_data(ttl=3600)
def fetch_scryfall_card(card_name):
    """Busca dados completos de uma carta no Scryfall."""
    if not card_name or not card_name.strip():
        return {"name": "", "found": False, "color_identity": [], "type_line": "", "image_url": ""}
    
    headers = {"User-Agent": "MTGCommanderAssistant/1.0", "Accept": "application/json"}
    encoded_name = requests.utils.quote(card_name.strip())
    url = f"[https://api.scryfall.com/cards/named?exact=](https://api.scryfall.com/cards/named?exact=){encoded_name}"
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code != 200:
            url = f"[https://api.scryfall.com/cards/named?fuzzy=](https://api.scryfall.com/cards/named?fuzzy=){encoded_name}"
            response = requests.get(url, headers=headers, timeout=5)
            
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
    """Puxa o banco do EDHREC e retorna métricas exatas de Inclusão e Sinergia."""
    headers = {"User-Agent": "MTGCommanderAssistant/1.0"}
    slug = commander_name.lower().replace("'", "").replace(",", "").replace(" ", "-")
    url = f"[https://json.edhrec.com/pages/commanders/](https://json.edhrec.com/pages/commanders/){slug}.json"
    
    edh_db = {}
    try:
        res = requests.get(url, headers=headers, timeout=10)
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

# --- BARRA LATERAL (CONFIGURAÇÕES E COMANDANTE / DUPLA DE COMANDANTES) ---
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

search_term_1 = st.sidebar.text_input(
    "Pesquisar Comandante 1:",
    placeholder="Ex: Atraxa, Frodo, Tymna...",
    key="search_cmd_1"
)
filtered_1 = search_commanders_scryfall(search_term_1)
cmd_1_name = st.sidebar.selectbox("Comandante Principal:", options=filtered_1, index=0, key="sel_cmd_1") if filtered_1 else None

cmd_2_name = None
if mode_commanders == "Parceiros / Dupla (2 Comandantes)":
    search_term_2 = st.sidebar.text_input(
        "Pesquisar Comandante 2 (Parceiro/Background):",
        placeholder="Ex: Kraum, Shadowheart...",
        key="search_cmd_2"
    )
    filtered_2 = search_commanders_scryfall(search_term_2)
    cmd_2_name = st.sidebar.selectbox("Segundo Comandante:", options=filtered_2, index=0, key="sel_cmd_2") if filtered_2 else None

if cmd_1_name:
    c1_data = fetch_scryfall_card(cmd_1_name)
    combined_colors = set(c1_data.get("color_identity", []))
    
    display_name = c1_data['name']
    images_to_show = [c1_data['image_url']] if c1_data['image_url'] else []
    
    if cmd_2_name:
        c2_data = fetch_scryfall_card(cmd_2_name)

import json
import requests
import streamlit as st
from PIL import Image
import google.generativeai as genai

st.set_page_config(page_title="MTG Commander Assistant", page_icon="🃏", layout="wide")

st.title("🃏 MTG Commander Assistant")
st.subheader("Protótipo 0.4 - Recomendação EDHREC & Sinergias High Lift")

# --- FUNÇÕES AUXILIARES DA API SCRYFALL ---
@st.cache_data(ttl=3600)
def fetch_scryfall_card(card_name):
    """Busca dados de uma carta no Scryfall pelo nome."""
    if not card_name or not card_name.strip():
        return {"name": "", "found": False, "color_identity": [], "type_line": "", "image_url": ""}
    
    headers = {
        "User-Agent": "MTGCommanderAssistant/1.0 (Personal Project)",
        "Accept": "application/json"
    }
    
    encoded_name = requests.utils.quote(card_name.strip())
    url = f"https://api.scryfall.com/cards/named?fuzzy={encoded_name}"
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
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
    """Verifica se a carta respeita a identidade de cor do comandante."""
    return set(card_colors).issubset(set(commander_colors))

# --- FUNÇÃO AUXILIAR EDHREC ---
@st.cache_data(ttl=3600)
def fetch_edhrec_recommendations(commander_name):
    """Puxa a lista de cartas mais usadas do EDHREC para o comandante."""
    headers = {"User-Agent": "MTGCommanderAssistant/1.0"}
    slug = commander_name.lower().replace("'", "").replace(",", "").replace(" ", "-")
    url = f"https://json.edhrec.com/pages/commanders/{slug}.json"
    
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            recommended_names = []
            container = data.get("container", {}).get("json_dict", {}).get("cardlists", [])
            for cardlist in container:
                for card in cardlist.get("cardviews", []):
                    recommended_names.append(card.get("name"))
            return list(set(recommended_names))
    except Exception:
        pass
    return []

# --- BARRA LATERAL ---
st.sidebar.header("⚙️ Configurações & Comandante")
api_key_input = st.sidebar.text_input("Gemini API Key:", type="password", help="Cole sua chave do Google AI Studio aqui")
api_key = api_key_input or st.secrets.get("GEMINI_API_KEY", "")

if not api_key:
    st.info("👈 Por favor, insira sua **Gemini API Key** na barra lateral para liberar as funções.")
    st.stop()

st.sidebar.success("✅ Chave da API ativa!")
st.sidebar.markdown("---")
st.sidebar.subheader("👑 Definir Comandante")
commander_name_input = st.sidebar.text_input("Nome do Comandante:", value="Atraxa, Praetors' Voice")

if commander_name_input:
    commander_data = fetch_scryfall_card(commander_name_input)
    if commander_data["found"]:
        st.sidebar.image(commander_data["image_url"], caption=f"Comandante: {commander_data['name']}", use_container_width=True)
        st.sidebar.caption(f"Cores: {', '.join(commander_data['color_identity']) if commander_data['color_identity'] else 'Incolor'}")
        st.session_state['commander_data'] = commander_data
    else:
        st.sidebar.error("Comandante não encontrado no Scryfall!")

# --- UPLOAD DE IMAGEM ---
uploaded_file = st.file_uploader("📷 Envie a foto de uma carta ou página do seu fichário:", type=["jpg", "jpeg", "png", "webp"])

if uploaded_file:
    col1, col2 = st.columns([1, 1])
    with col1:
        image = Image.open(uploaded_file)
        st.image(image, caption="Foto enviada", use_container_width=True)
    
    with col2:
        if st.button("🔍 Escanear e Listar Cartas", type="primary"):
            with st.spinner("Analisando a imagem com a IA..."):
                try:
                    genai.configure(api_key=api_key)
                    prompt = """
                    Você é um especialista em Magic: The Gathering (MTG).
                    Analise a imagem enviada (pode ser uma carta individual ou uma página de fichário com várias cartas).
                    Identifique todas as cartas de MTG visíveis.
                    
                    Regras:
                    1. Identifique o nome OFICIAL da carta em INGLÊS.
                    2. Responda APENAS com um array JSON válido contendo objetos com 'card_name' (string) e 'qty' (integer).
                    3. Não escreva nenhuma introdução, explicação ou texto fora do JSON.
                    """
                    
                    candidate_models = ['gemini-1.5-flash', 'gemini-2.0-flash', 'gemini-2.5-flash', 'gemini-3.6-flash', 'gemini-1.5-pro']
                    response = None
                    for m in candidate_models:
                        try:
                            model = genai.GenerativeModel(m)
                            response = model.generate_content([prompt, image])
                            break
                        except Exception:
                            continue
                    
                    if not response:
                        raise Exception("Não foi possível conectar a nenhum modelo ativo.")
                    
                    raw_text = response.text.strip()
                    if "```" in raw_text:
                        parts = raw_text.split("```")
                        for part in parts:
                            clean_part = part.strip()
                            if clean_part.startswith("json"):
                                clean_part = clean_part[4:].strip()
                            if clean_part.startswith("["):
                                raw_text = clean_part
                                break
                    
                    cards_data = json.loads(raw_text)
                    st.session_state['detected_cards'] = cards_data
                    st.success(f"✨ {len(cards_data)} carta(s) detectada(s)!")
                    
                except Exception as e:
                    st.error(f"Erro de processamento: {e}")

# --- VALIDAÇÃO E EXIBIÇÃO ---
if 'detected_cards' in st.session_state and st.session_state['detected_cards']:
    st.markdown("---")
    st.write("### 📋 Sua Coleção x Comandante")
    
    if st.button("🔄 Validar Cartas no Scryfall"):
        with st.spinner("Buscando dados das cartas no Scryfall..."):
            validated_list = []
            cmd_colors = st.session_state.get('commander_data', {}).get('color_identity', [])
            
            for item in st.session_state['detected_cards']:
                scry_info = fetch_scryfall_card(item['card_name'])
                if scry_info['found']:
                    valid = is_color_valid(scry_info['color_identity'], cmd_colors) if 'commander_data' in st.session_state else True
                    validated_list.append({
                        "Carta": scry_info['name'],
                        "Qtd": item['qty'],
                        "Tipo": scry_info['type_line'],
                        "Cores": ", ".join(scry_info['color_identity']) if scry_info['color_identity'] else "Incolor",
                        "Valida no Commander": "✅ Sim" if valid else "❌ Fora da Cor",
                        "Imagem": scry_info['image_url'],
                        "OracleText": scry_info['oracle_text']
                    })
                else:
                    validated_list.append({
                        "Carta": item['card_name'],
                        "Qtd": item['qty'],
                        "Tipo": "Não encontrada",
                        "Cores": "-",
                        "Valida no Commander": "❓ Desconhecido",
                        "Imagem": "",
                        "OracleText": ""
                    })
            st.session_state['validated_list'] = validated_list

    if 'validated_list' in st.session_state:
        st.dataframe(st.session_state['validated_list'], use_container_width=True)
        
        # --- MOTOR DE RECOMENDAÇÃO & SINERGIA HIGH-LIFT ---
        st.markdown("---")
        st.write("### 🚀 Motor de Recomendação & Sinergia High-Lift")
        
        if st.button("✨ Analisar Sinergias e Montar Deck", type="primary"):
            with st.spinner("Cruzo dados com EDHREC e calculando sinergias 'High Lift'..."):
                try:
                    cmd_name = st.session_state.get('commander_data', {}).get('name', 'Comandante')
                    valid_cards = [c for c in st.session_state['validated_list'] if "✅" in c['Valida no Commander']]
                    
                    # 1. Busca EDHREC
                    edhrec_staples = fetch_edhrec_recommendations(cmd_name)
                    
                    # Separa quais da coleção do usuário estão no EDHREC
                    matched_edhrec = [c['Carta'] for c in valid_cards if any(e.lower() in c['Carta'].lower() for e in edhrec_staples)]
                    
                    # 2. IA para Sinergia High-Lift entre as 99
                    genai.configure(api_key=api_key)
                    
                    cards_summary = "\n".join([f"- {c['Carta']} ({c['Tipo']}): {c['OracleText'][:100]}" for c in valid_cards])
                    
                    synergy_prompt = f"""
                    Você é um estrategista mestre de Magic: The Gathering Commander (EDH).
                    
                    Comandante: {cmd_name}
                    
                    Cartas disponíveis no fichário do jogador (apenas as válidas nas cores):
                    {cards_summary}
                    
                    Cartas da lista que também aparecem como Staples do EDHREC para esse comandante:
                    {', '.join(matched_edhrec) if matched_edhrec else 'Nenhuma casada diretamente'}
                    
                    Sua tarefa:
                    1. Identifique as **Sinergias "High Lift" (Carta com Carta)** entre as cartas do fichário do jogador. Mostre como cartas específicas interagem muito bem juntas, criando engines (ex: marcadores, sacrifício, compra de cartas, remoção em massa sinérgica).
                    2. Crie uma **Sugestão de Núcleo de Deck** aproveitando ao máximo as cartas do jogador.
                    3. Liste 3 a 5 **Sugestões de Compras Baratas (Upgrade)** que teriam sinergia absurda com o que ele JÁ TEM no fichário.
                    
                    Responda em Português, com formatação clara em tópicos e emojis.
                    """
                    
                    candidate_models = ['gemini-1.5-flash', 'gemini-2.0-flash', 'gemini-2.5-flash', 'gemini-3.6-flash', 'gemini-1.5-pro']
                    analysis_res = None
                    for m in candidate_models:
                        try:
                            model = genai.GenerativeModel(m)
                            analysis_res = model.generate_content(synergy_prompt)
                            break
                        except Exception:
                            continue
                    
                    st.markdown("## 📊 Relatório Estratégico de Deckbuilding")
                    st.write(analysis_res.text)
                    
                    # Lista exportável para Moxfield/Archidekt
                    st.markdown("### 📥 Exportar Lista de Cartas Selecionadas:")
                    export_text = f"1 {cmd_name} *CMDR*\n" + "\n".join([f"1 {c['Carta']}" for c in valid_cards])
                    st.text_area("Copie e cole direto no Moxfield/Archidekt/ManaBox:", value=export_text, height=150)
                    
                except Exception as e:
                    st.error(f"Erro ao gerar análise: {e}")

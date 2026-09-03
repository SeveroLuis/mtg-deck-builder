import json
import requests
import streamlit as st
from PIL import Image
import google.generativeai as genai

st.set_page_config(page_title="MTG Commander Assistant", page_icon="🃏", layout="wide")

st.title("🃏 MTG Commander Assistant")
st.subheader("Protótipo 0.5 - Análise Objetiva com Dados Reais do EDHREC")

# --- FUNÇÕES AUXILIARES SCRYFALL ---
@st.cache_data(ttl=3600)
def fetch_scryfall_card(card_name):
    """Busca dados de uma carta no Scryfall pelo nome."""
    if not card_name or not card_name.strip():
        return {"name": "", "found": False, "color_identity": [], "type_line": "", "image_url": ""}
    
    headers = {"User-Agent": "MTGCommanderAssistant/1.0", "Accept": "application/json"}
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
    return set(card_colors).issubset(set(commander_colors))

# --- FUNÇÃO EDHREC COM EXTRAÇÃO DE MÉTRICAS REAIS ---
@st.cache_data(ttl=3600)
def fetch_edhrec_full_metrics(commander_name):
    """Puxa o banco do EDHREC e retorna métricas exatas de Inclusão e Sinergia por carta."""
    headers = {"User-Agent": "MTGCommanderAssistant/1.0"}
    slug = commander_name.lower().replace("'", "").replace(",", "").replace(" ", "-")
    url = f"https://json.edhrec.com/pages/commanders/{slug}.json"
    
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
                    syn_pct = f"{int(synergy_val * 100):+d}%" if synergy_val else "N/A"
                    label = card.get("label", "N/A") # ex: "65% of 12000 decks"
                    
                    edh_db[c_name.lower()] = {
                        "name": c_name,
                        "synergy": syn_pct,
                        "inclusion": label,
                        "category": header_category
                    }
    except Exception:
        pass
    return edh_db

# --- BARRA LATERAL ---
st.sidebar.header("⚙️ Configurações & Comandante")
api_key_input = st.sidebar.text_input("Gemini API Key:", type="password")
api_key = api_key_input or st.secrets.get("GEMINI_API_KEY", "")

if not api_key:
    st.info("👈 Insira sua **Gemini API Key** na barra lateral para continuar.")
    st.stop()

st.sidebar.success("✅ API Ativa")
st.sidebar.markdown("---")
st.sidebar.subheader("👑 Comandante")
commander_name_input = st.sidebar.text_input("Nome do Comandante:", value="Atraxa, Praetors' Voice")

if commander_name_input:
    commander_data = fetch_scryfall_card(commander_name_input)
    if commander_data["found"]:
        st.sidebar.image(commander_data["image_url"], caption=f"Comandante: {commander_data['name']}", use_container_width=True)
        st.session_state['commander_data'] = commander_data

# --- UPLOAD DE FOTO DO FICHÁRIO ---
uploaded_file = st.file_uploader("📷 Envie a foto das cartas ou página do fichário:", type=["jpg", "jpeg", "png", "webp"])

if uploaded_file:
    col1, col2 = st.columns([1, 1])
    with col1:
        image = Image.open(uploaded_file)
        st.image(image, caption="Foto enviada", use_container_width=True)
    
    with col2:
        if st.button("🔍 Escanear e Listar Cartas", type="primary"):
            with st.spinner("Analisando imagem..."):
                try:
                    genai.configure(api_key=api_key)
                    prompt = """
                    Analise a imagem enviada. Liste as cartas de MTG visíveis.
                    Responda APENAS com JSON array: [{"card_name": "Sol Ring", "qty": 1}]
                    Nome oficial em inglês.
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
                    
                    raw_text = response.text.strip()
                    if "```" in raw_text:
                        parts = raw_text.split("```")
                        for part in parts:
                            clean_part = part.strip()
                            if clean_part.startswith("json"): clean_part = clean_part[4:].strip()
                            if clean_part.startswith("["): raw_text = clean_part; break
                    
                    st.session_state['detected_cards'] = json.loads(raw_text)
                    st.success("Cartas detectadas!")
                except Exception as e:
                    st.error(f"Erro: {e}")

# --- PROCESSAMENTO E EXIBIÇÃO DE DADOS OBJETIVOS ---
if 'detected_cards' in st.session_state and st.session_state['detected_cards']:
    st.markdown("---")
    st.write("### 📋 Validação da Coleção")
    
    if st.button("🔄 Validar no Scryfall e EDHREC"):
        with st.spinner("Buscando dados estatísticos oficiais..."):
            cmd_name = st.session_state.get('commander_data', {}).get('name', '')
            cmd_colors = st.session_state.get('commander_data', {}).get('color_identity', [])
            
            # Carrega banco de dados real do EDHREC para o Comandante
            edhrec_db = fetch_edhrec_full_metrics(cmd_name)
            
            validated_list = []
            for item in st.session_state['detected_cards']:
                scry = fetch_scryfall_card(item['card_name'])
                if scry['found']:
                    valid = is_color_valid(scry['color_identity'], cmd_colors)
                    
                    # Checa dados reais no EDHREC
                    edh_info = edhrec_db.get(scry['name'].lower(), {})
                    
                    validated_list.append({
                        "Carta": scry['name'],
                        "Qtd": item['qty'],
                        "Valida": "✅ Sim" if valid else "❌ Fora da Cor",
                        "Inclusão EDHREC": edh_info.get("inclusion", "Fora do Top EDHREC"),
                        "Sinergia EDHREC": edh_info.get("synergy", "0%"),
                        "Categoria EDHREC": edh_info.get("category", "Geral/Outros"),
                        "OracleText": scry['oracle_text'],
                        "Tipo": scry['type_line']
                    })
            st.session_state['validated_list'] = validated_list

    if 'validated_list' in st.session_state:
        st.dataframe(st.session_state['validated_list'], use_container_width=True)
        
        st.markdown("---")
        st.write("### 📊 Relatório Estatístico e Objetivo para Deckbuilding")
        
        if st.button("✨ Gerar Resumo Estruturado de Deck", type="primary"):
            with st.spinner("Compilando análise objetiva baseada em estatísticas..."):
                try:
                    cmd_name = st.session_state.get('commander_data', {}).get('name', 'Comandante')
                    valid_cards = [c for c in st.session_state['validated_list'] if "✅" in c['Valida']]
                    
                    cards_data_prompt = "\n".join([
                        f"- {c['Carta']} | Categoria EDHREC: {c['Categoria EDHREC']} | Inclusão: {c['Inclusão EDHREC']} | Sinergia: {c['Sinergia EDHREC']} | Texto: {c['OracleText'][:80]}"
                        for c in valid_cards
                    ])
                    
                    prompt = f"""
                    Você é um analista estatístico de MTG Commander. Seja EXTREMAMENTE OBJETIVO e DIRETO. Sem texto explicativo longo, sem introduções ou saudações.

                    Comandante: {cmd_name}
                    
                    Dados REAIS das cartas do jogador (extraídos do EDHREC e Scryfall):
                    {cards_data_prompt}

                    Gere o relatório no seguinte formato estrito:

                    ### 🎯 Cartas Recomendadas da Coleção (Dados EDHREC)
                    Crie uma tabela Markdown contendo:
                    | Carta | Categoria Funcional | Inclusão (%) [Fonte: EDHREC] | Sinergia (%) [Fonte: EDHREC] | Função Prática no Deck |

                    ### 🔗 Sinergias Diretas Carta-com-Carta (Pares Concretos)
                    Apenas pares práticos de 2 cartas que interagem diretamente (ex: Carta A + Carta B). Liste como bullet points curtos:
                    - **[Carta A] + [Carta B]**: [Explicação de no máximo 10 palavras da interação direta].

                    ### ⚠️ Observações de Deckbuilding
                    - Liste no máximo 3 bullets ultracurtos sobre o equilíbrio do deck (Rampa, Terrenos ou Remoção que faltam).
                    """
                    
                    genai.configure(api_key=api_key)
                    candidate_models = ['gemini-1.5-flash', 'gemini-2.0-flash', 'gemini-2.5-flash', 'gemini-3.6-flash', 'gemini-1.5-pro']
                    res = None
                    for m in candidate_models:
                        try:
                            model = genai.GenerativeModel(m)
                            res = model.generate_content(prompt)
                            break
                        except Exception:
                            continue
                            
                    st.markdown(res.text)
                    
                    # Caixa de texto limpa para cópia
                    st.markdown("### 📥 Lista para Cópia (Moxfield / ManaBox):")
                    export_text = f"1 {cmd_name}\n" + "\n".join([f"1 {c['Carta']}" for c in valid_cards])
                    st.text_area("Copia e cola:", value=export_text, height=120)
                    
                except Exception as e:
                    st.error(f"Erro: {e}")

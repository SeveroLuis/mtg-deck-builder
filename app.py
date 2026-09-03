import json
import requests
import streamlit as st
from PIL import Image
import google.generativeai as genai

st.set_page_config(page_title="MTG Commander Assistant", page_icon="🃏", layout="wide")

st.title("🃏 MTG Commander Assistant")
st.subheader("Protótipo 0.6 - Autocomplete, Multi-Upload e Análise Cirúrgica")

# --- FUNÇÃO AUTOCOMPLETE DO SCRYFALL ---
@st.cache_data(ttl=3600)
def autocomplete_scryfall_card(query):
    """Busca sugestões de nomes de cartas no Scryfall em tempo real."""
    if not query or len(query.strip()) < 2:
        return []
    headers = {"User-Agent": "MTGCommanderAssistant/1.0", "Accept": "application/json"}
    url = f"https://api.scryfall.com/cards/autocomplete?q={requests.utils.quote(query.strip())}"
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            return res.json().get("data", [])
    except Exception:
        pass
    return []

# --- FUNÇÕES AUXILIARES SCRYFALL & EDHREC ---
@st.cache_data(ttl=3600)
def fetch_scryfall_card(card_name):
    """Busca dados completos de uma carta no Scryfall."""
    if not card_name or not card_name.strip():
        return {"name": "", "found": False, "color_identity": [], "type_line": "", "image_url": ""}
    
    headers = {"User-Agent": "MTGCommanderAssistant/1.0", "Accept": "application/json"}
    encoded_name = requests.utils.quote(card_name.strip())
    url = f"https://api.scryfall.com/cards/named?exact={encoded_name}"
    
    # Se der erro com exact, tenta fuzzy
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code != 200:
            url = f"https://api.scryfall.com/cards/named?fuzzy={encoded_name}"
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
                    label = card.get("label", "N/A")
                    
                    edh_db[c_name.lower()] = {
                        "name": c_name,
                        "synergy": syn_pct,
                        "inclusion": label,
                        "category": header_category
                    }
    except Exception:
        pass
    return edh_db

# --- BARRA LATERAL (AUTOCOMPLETE DE COMANDANTE) ---
st.sidebar.header("⚙️ Configurações & Comandante")
api_key_input = st.sidebar.text_input("Gemini API Key:", type="password")
api_key = api_key_input or st.secrets.get("GEMINI_API_KEY", "")

if not api_key:
    st.info("👈 Insira sua **Gemini API Key** na barra lateral para continuar.")
    st.stop()

st.sidebar.success("✅ API Ativa")
st.sidebar.markdown("---")
st.sidebar.subheader("👑 Escolher Comandante")

# Busca dinamicamente conforme o usuário digita
cmd_search_query = st.sidebar.text_input("Digite o nome (ex: Atraxa, Krenko...):", value="Atraxa")
suggestions = autocomplete_scryfall_card(cmd_search_query)

if suggestions:
    selected_commander = st.sidebar.selectbox("Sugestões encontradas no Scryfall:", options=suggestions)
else:
    selected_commander = cmd_search_query

if selected_commander:
    commander_data = fetch_scryfall_card(selected_commander)
    if commander_data["found"]:
        st.sidebar.image(commander_data["image_url"], caption=f"Comandante: {commander_data['name']}", use_container_width=True)
        st.sidebar.caption(f"Identidade: {', '.join(commander_data['color_identity']) if commander_data['color_identity'] else 'Incolor'}")
        st.session_state['commander_data'] = commander_data
    else:
        st.sidebar.error("Comandante não encontrado. Digite mais letras.")

# --- UPLOAD MULTI-IMAGEM DE FICHÁRIOS ---
st.write("### 📸 Leitura de Coleção e Fichários")
uploaded_files = st.file_uploader(
    "Envie as fotos das páginas do seu fichário (Pode selecionar VÁRIAS fotos de uma vez!):",
    type=["jpg", "jpeg", "png", "webp"],
    accept_multiple_files=True
)

if uploaded_files:
    st.write(f"📁 **{len(uploaded_files)} foto(s) carregada(s).**")
    
    with st.expander("👁️ Ver fotos enviadas", expanded=False):
        cols = st.columns(min(4, len(uploaded_files)))
        for idx, file in enumerate(uploaded_files):
            cols[idx % 4].image(Image.open(file), caption=file.name, use_container_width=True)
            
    if st.button("🔍 Escanear Todas as Fotos e Compilar Coleção", type="primary"):
        all_cards_map = {}
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        genai.configure(api_key=api_key)
        candidate_models = ['gemini-1.5-flash', 'gemini-2.0-flash', 'gemini-2.5-flash', 'gemini-3.6-flash', 'gemini-1.5-pro']
        
        for idx, file in enumerate(uploaded_files):
            status_text.text(f"Analisando imagem {idx+1} de {len(uploaded_files)} ({file.name})...")
            image = Image.open(file)
            
            prompt = """
            Analise a imagem enviada (página de fichário com cartas de MTG).
            Identifique todas as cartas de MTG visíveis.
            Responda APENAS com um array JSON válido:
            [{"card_name": "Sol Ring", "qty": 1}]
            Nome oficial em inglês.
            """
            
            response = None
            for m in candidate_models:
                try:
                    model = genai.GenerativeModel(m)
                    response = model.generate_content([prompt, image])
                    break
                except Exception:
                    continue
            
            if response:
                try:
                    raw_text = response.text.strip()
                    if "```" in raw_text:
                        parts = raw_text.split("```")
                        for part in parts:
                            clean_part = part.strip()
                            if clean_part.startswith("json"): clean_part = clean_part[4:].strip()
                            if clean_part.startswith("["): raw_text = clean_part; break
                    
                    cards_list = json.loads(raw_text)
                    for item in cards_list:
                        name = item.get("card_name", "").strip()
                        qty = int(item.get("qty", 1))
                        if name:
                            key = name.lower()
                            if key in all_cards_map:
                                all_cards_map[key]["qty"] += qty
                            else:
                                all_cards_map[key] = {"card_name": name, "qty": qty}
                except Exception:
                    pass
            
            progress_bar.progress((idx + 1) / len(uploaded_files))
            
        status_text.empty()
        compiled_list = list(all_cards_map.values())
        st.session_state['detected_cards'] = compiled_list
        st.success(f"✨ Compilação concluída! {len(compiled_list)} carta(s) única(s) identificadas no total.")

# --- VALIDAÇÃO E RELATÓRIO CIRÚRGICO ---
if 'detected_cards' in st.session_state and st.session_state['detected_cards']:
    st.markdown("---")
    st.write("### 📋 Sua Coleção x Comandante")
    
    if st.button("🔄 Validar Coleção no Scryfall e EDHREC"):
        with st.spinner("Buscando dados no EDHREC e Scryfall..."):
            cmd_name = st.session_state.get('commander_data', {}).get('name', '')
            cmd_colors = st.session_state.get('commander_data', {}).get('color_identity', [])
            
            edhrec_db = fetch_edhrec_full_metrics(cmd_name)
            validated_list = []
            
            for item in st.session_state['detected_cards']:
                scry = fetch_scryfall_card(item['card_name'])
                if scry['found']:
                    valid = is_color_valid(scry['color_identity'], cmd_colors)
                    edh_info = edhrec_db.get(scry['name'].lower(), {})
                    
                    validated_list.append({
                        "Carta": scry['name'],
                        "Qtd": item['qty'],
                        "Valida": "✅ Sim" if valid else "❌ Fora da Cor",
                        "Inclusão EDHREC": edh_info.get("inclusion", "Fora do Top EDHREC"),
                        "Sinergia EDHREC": edh_info.get("synergy", "0%"),
                        "Categoria EDHREC": edh_info.get("category", "Geral/Outros"),
                        "OracleText": scry['oracle_text']
                    })
            st.session_state['validated_list'] = validated_list

    if 'validated_list' in st.session_state:
        st.dataframe(st.session_state['validated_list'], use_container_width=True)
        
        st.markdown("---")
        st.write("### ⚡ Análise Cirúrgica de Aproveitamento da Coleção")
        
        if st.button("✨ Gerar Análise de Sinergias Diretas", type="primary"):
            with st.spinner("Analisando interações cirúrgicas carta-com-carta..."):
                try:
                    cmd_name = st.session_state.get('commander_data', {}).get('name', 'Comandante')
                    valid_cards = [c for c in st.session_state['validated_list'] if "✅" in c['Valida']]
                    
                    cards_data_prompt = "\n".join([
                        f"- {c['Carta']} | Categoria: {c['Categoria EDHREC']} | Inclusão: {c['Inclusão EDHREC']} | Sinergia: {c['Sinergia EDHREC']} | Texto: {c['OracleText'][:80]}"
                        for c in valid_cards
                    ])
                    
                    prompt = f"""
                    Você é um analista estatístico de MTG Commander. Seja EXTREMAMENTE OBJETIVO, CIRÚRGICO e DIRETO. Sem introduções, saudações ou conselhos de deckbuilding geral.

                    Comandante: {cmd_name}
                    
                    Coleção escaneada do jogador:
                    {cards_data_prompt}

                    Gere a análise ESTRITAMENTE nas 2 seções abaixo (não adicione nenhuma outra seção):

                    ### 🎯 Cartas Aproveitáveis da Coleção (Dados EDHREC)
                    Crie uma tabela Markdown contendo:
                    | Carta | Categoria Funcional | Inclusão (%) [Fonte: EDHREC] | Sinergia (%) [Fonte: EDHREC] | Função no Deck |

                    ### 🔗 Sinergias Diretas Carta-com-Carta (Pares Concretos)
                    Liste apenas duplas de cartas do fichário do jogador que interagem de forma direta e comprovada no jogo (ex: Carta A + Carta B). Separe as duplas que realmente "dão jogo" e funcionam.
                    Use bullet points curtos:
                    - **[Carta A] + [Carta B]**: [Explicação cirúrgica de no máximo 10 palavras da interação].
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
                    
                    st.markdown("### 📥 Exportar Lista Selecionada:")
                    export_text = f"1 {cmd_name}\n" + "\n".join([f"1 {c['Carta']}" for c in valid_cards])
                    st.text_area("Copiar para Moxfield/ManaBox:", value=export_text, height=120)
                    
                except Exception as e:
                    st.error(f"Erro: {e}")

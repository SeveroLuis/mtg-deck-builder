import json
import requests
import streamlit as st
from PIL import Image
import io
import google.generativeai as genai

st.set_page_config(page_title="MTG Commander Assistant", layout="wide")

st.title("MTG Commander Assistant")
st.subheader("Protótipo 0.7.3 - Triagem, Sinergias e Otimização")

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

# --- BARRA LATERAL (AUTOCOMPLETE DE COMANDANTE) ---
st.sidebar.header("Configurações e Comandante")
api_key_input = st.sidebar.text_input("Gemini API Key:", type="password")
api_key = api_key_input or st.secrets.get("GEMINI_API_KEY", "")

if not api_key:
    st.info("Insira sua Gemini API Key na barra lateral para continuar.")
    st.stop()

st.sidebar.success("API Ativa")
st.sidebar.markdown("---")
st.sidebar.subheader("Escolher Comandante")

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
st.write("### Leitura de Coleção e Fichários em Lote")
uploaded_files = st.file_uploader(
    "Envie as fotos das páginas do seu fichário (Selecione múltiplas fotos de uma vez):",
    type=["jpg", "jpeg", "png", "webp"],
    accept_multiple_files=True
)

if uploaded_files:
    st.write(f"**{len(uploaded_files)} foto(s) carregada(s).**")
    
    with st.expander("Ver fotos carregadas", expanded=False):
        cols = st.columns(min(4, len(uploaded_files)))
        for idx, file in enumerate(uploaded_files):
            cols[idx % 4].image(Image.open(file), caption=file.name, use_container_width=True)
            
    if st.button("Escanear Todas as Fotos e Compilar Coleção", type="primary"):
        all_cards_map = {}
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        failed_images = []
        
        for idx, file in enumerate(uploaded_files):
            status_text.text(f"Otimizando e analisando imagem {idx+1} de {len(uploaded_files)} ({file.name})...")
            try:
                raw_img = Image.open(file)
                optimized_img = compress_image_for_api(raw_img)
                
                prompt = """
                Analise a imagem enviada (página de fichário com cartas de MTG).
                Identifique todas as cartas de MTG visíveis.
                Responda APENAS com um array JSON válido:
                [{"card_name": "Sol Ring", "qty": 1}]
                Nome oficial em inglês.
                """
                
                raw_text = call_gemini_api(api_key, prompt, optimized_img)
                
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
                failed_images.append(file.name)
            
            progress_bar.progress((idx + 1) / len(uploaded_files))
            
        status_text.empty()
        compiled_list = list(all_cards_map.values())
        st.session_state['detected_cards'] = compiled_list
        
        if failed_images:
            st.warning(f"Atenção: {len(failed_images)} imagem(ns) não puderam ser lidas ({', '.join(failed_images)}). As demais foram processadas.")
        st.success(f"Compilação concluída! {len(compiled_list)} carta(s) única(s) identificadas no total.")

# --- VALIDAÇÃO E ABAS "DÁ JOGO" VS "FORA DO RADAR" ---
if 'detected_cards' in st.session_state and st.session_state['detected_cards']:
    st.markdown("---")
    st.write("### Triagem da Coleção vs Comandante")
    
    if st.button("Validar Coleção no Scryfall e EDHREC"):
        with st.spinner("Buscando dados estatísticos no EDHREC e Scryfall..."):
            cmd_name = st.session_state.get('commander_data', {}).get('name', '')
            cmd_colors = st.session_state.get('commander_data', {}).get('color_identity', [])
            
            edhrec_db = fetch_edhrec_full_metrics(cmd_name)
            
            playable_cards = []
            junk_cards = []
            
            for item in st.session_state['detected_cards']:
                scry = fetch_scryfall_card(item['card_name'])
                if scry['found']:
                    valid = is_color_valid(scry['color_identity'], cmd_colors)
                    edh_info = edhrec_db.get(scry['name'].lower(), {})
                    
                    raw_syn = edh_info.get("synergy_raw", 0)
                    has_edh_data = edh_info.get("inclusion") is not None
                    
                    card_dict = {
                        "Carta": scry['name'],
                        "Qtd": item['qty'],
                        "Valida": "Sim" if valid else "Fora da Cor",
                        "Inclusão EDHREC": edh_info.get("inclusion", "Fora do Top EDHREC"),
                        "Sinergia EDHREC": edh_info.get("synergy", "0%"),
                        "Categoria EDHREC": edh_info.get("category", "Geral/Outros"),
                        "OracleText": scry['oracle_text']
                    }
                    
                    if not valid:
                        junk_cards.append(card_dict)
                    elif has_edh_data or raw_syn > 0:
                        playable_cards.append(card_dict)
                    else:
                        junk_cards.append(card_dict)
            
            st.session_state['playable_cards'] = playable_cards
            st.session_state['junk_cards'] = junk_cards

    if 'playable_cards' in st.session_state:
        tab1, tab2 = st.tabs([
            f"Aproveitáveis ({len(st.session_state['playable_cards'])} cartas)",
            f"Fora do Radar / Descarte ({len(st.session_state['junk_cards'])} cartas)"
        ])
        
        with tab1:
            st.markdown("**Cartas com sinergia ou presença confirmada no EDHREC para este comandante:**")
            if st.session_state['playable_cards']:
                st.dataframe(st.session_state['playable_cards'], use_container_width=True)
            else:
                st.info("Nenhuma carta com sinergia estatística direta encontrada.")
                
        with tab2:
            st.markdown("**Cartas que cabem na cor, mas não possuem destaque nos dados do EDHREC:**")
            if st.session_state['junk_cards']:
                st.dataframe(st.session_state['junk_cards'], use_container_width=True)
            else:
                st.info("Nenhuma carta descartável encontrada.")
        
        st.markdown("---")
        st.write("### Análise Cirúrgica de Sinergias Cruzadas")
        
        if st.button("Gerar Matriz de Sinergias Carta-com-Carta", type="primary"):
            with st.spinner("Analisando interações diretas entre as cartas do fichário..."):
                try:
                    cmd_name = st.session_state.get('commander_data', {}).get('name', 'Comandante')
                    valid_playables = [c for c in st.session_state['playable_cards'] if c['Valida'] == "Sim"]
                    
                    if not valid_playables:
                        st.warning("Não há cartas válidas e aproveitáveis suficientes para cruzar sinergias.")
                    else:
                        cards_data_prompt = "\n".join([
                            f"- {c['Carta']} | Categoria: {c['Categoria EDHREC']} | Sinergia EDHREC: {c['Sinergia EDHREC']} | Texto: {c['OracleText'][:80]}"
                            for c in valid_playables
                        ])
                        
                        prompt = f"""
                        Você é um analista estatístico de MTG Commander. Seja EXTREMAMENTE OBJETIVO, CIRÚRGICO e DIRETO. Sem introduções, saudações ou dicas de deckbuilding geral.

                        Comandante: {cmd_name}
                        
                        Cartas aproveitáveis da coleção do jogador:
                        {cards_data_prompt}

                        Gere a análise ESTRITAMENTE nas 2 seções abaixo (não adicione nenhuma outra seção):

                        ### Cartas Recomendadas da Coleção (Dados EDHREC)
                        Crie uma tabela Markdown contendo:
                        | Carta | Categoria Funcional | Inclusão (%) [Fonte: EDHREC] | Sinergia (%) [Fonte: EDHREC] | Função no Deck |

                        ### Matriz de Sinergias Cruzadas do Fichário (Carta-com-Carta)
                        Analise especificamente como as cartas escaneadas do jogador interagem ENTRE SI e com o comandante.
                        Liste apenas duplas concretas de cartas presentes na coleção do jogador (ex: Carta A + Carta B).
                        Use bullet points curtos:
                        - **[Carta A] + [Carta B]**: [Explicação cirúrgica de no máximo 10 palavras da interação direta].
                        """
                        
                        res_text = call_gemini_api(api_key, prompt)
                        st.markdown(res_text)
                        
                        # Caixa de exportação no formato universal
                        st.markdown("### Exportar Lista para Deckbuilder:")
                        all_valid = valid_playables + [c for c in st.session_state['junk_cards'] if c['Valida'] == "Sim"]
                        export_text = f"1 {cmd_name}\n" + "\n".join([f"1 {c['Carta']}" for c in all_valid])
                        st.text_area("Copiar para Moxfield / ManaBox / Archidekt:", value=export_text, height=140)
                    
                except Exception as e:
                    st.error(f"Erro no processamento: {e}")

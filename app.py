import json
import streamlit as st
from PIL import Image
import google.generativeai as genai

st.set_page_config(page_title="MTG Commander Assistant", page_icon="🃏", layout="wide")

st.title("🃏 MTG Commander Assistant")
st.subheader("Protótipo 0.2 - Visão de IA para Cartas e Fichários")

# Barra lateral para configurações
st.sidebar.header("⚙️ Configurações")
api_key_input = st.sidebar.text_input("Gemini API Key:", type="password", help="Cole sua chave do Google AI Studio aqui")

api_key = api_key_input or st.secrets.get("GEMINI_API_KEY", "")

if not api_key:
    st.info("👈 Por favor, insira sua **Gemini API Key** na barra lateral para liberar o scanner.")
    st.stop()

st.sidebar.success("✅ Chave da API ativa!")

uploaded_file = st.file_uploader("📷 Envie a foto de uma carta ou página do seu fichário:", type=["jpg", "jpeg", "png", "webp"])

if uploaded_file:
    col1, col2 = st.columns([1, 1])
    
    with col1:
        image = Image.open(uploaded_file)
        st.image(image, caption="Foto enviada", use_container_width=True)
    
    with col2:
        if st.button("🔍 Escanear e Listar Cartas", type="primary"):
            with st.spinner("Buscando modelo ativo e analisando a imagem..."):
                try:
                    genai.configure(api_key=api_key)
                    
                    # Auto-detecção de modelos disponíveis na sua chave
                    all_models = list(genai.list_models())
                    valid_models = [
                        m.name for m in all_models 
                        if 'generateContent' in m.supported_generation_methods
                    ]
                    
                    if not valid_models:
                        st.error("Nenhum modelo de geração de conteúdo encontrado para sua API Key.")
                        st.stop()
                    
                    # Escolhe preferencialmente um modelo 'flash', ou pega o primeiro ativo
                    selected_model = next((m for m in valid_models if 'flash' in m.lower()), valid_models[0])
                    
                    model = genai.GenerativeModel(selected_model)
                    
                    prompt = """
                    Você é um especialista em Magic: The Gathering (MTG).
                    Analise a imagem enviada (pode ser uma carta individual ou uma página de fichário com várias cartas).
                    Identifique todas as cartas de MTG visíveis.
                    
                    Regras:
                    1. Identifique o nome OFICIAL da carta em INGLÊS (mesmo que a carta na foto esteja em português).
                    2. Responda APENAS com um array JSON válido contendo objetos com 'card_name' (string) e 'qty' (integer).
                    3. Não escreva nenhuma introdução, explicação ou texto fora do JSON.
                    
                    Exemplo de resposta:
                    [
                        {"card_name": "Sol Ring", "qty": 1},
                        {"card_name": "Command Tower", "qty": 1}
                    ]
                    """
                    
                    response = model.generate_content([prompt, image])
                    
                    raw_text = response.text.strip()
                    
                    # Remove formatação de código markdown caso venha
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
                    st.success(f"✨ {len(cards_data)} carta(s) identificada(s) usando o modelo ({selected_model.replace('models/', '')})!")
                    
                except Exception as e:
                    st.error(f"Erro de processamento: {e}")

if 'detected_cards' in st.session_state and st.session_state['detected_cards']:
    st.markdown("---")
    st.write("### 📋 Cartas Detectadas na sua Coleção:")
    st.caption("Você pode clicar diretamente nas células para editar ou corrigir qualquer nome de carta.")
    
    edited_cards = st.data_editor(
        st.session_state['detected_cards'],
        num_rows="dynamic",
        use_container_width=True,
        key="card_editor"
    )

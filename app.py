import json
import streamlit as st
from PIL import Image
from google import genai

st.set_page_config(page_title="MTG Commander Assistant", page_icon="🃏", layout="wide")

st.title("🃏 MTG Commander Assistant")
st.subheader("Protótipo 0.2 - Visão de IA para Cartas e Fichários")

# Barra lateral para configurações
st.sidebar.header("⚙️ Configurações")
api_key_input = st.sidebar.text_input("Gemini API Key:", type="password", help="Cole sua chave do Google AI Studio aqui")

# Pega a chave da barra lateral ou dos segredos do Streamlit
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
            with st.spinner("O Gemini está analisando a imagem..."):
                try:
                    client = genai.Client(api_key=api_key)
                    prompt = """
                    Você é um especialista em Magic: The Gathering (MTG).
                    Analise a imagem enviada (pode ser uma carta individual ou uma página de fichário com várias cartas).
                    Identifique todas as cartas de MTG visíveis.
                    
                    Regras:
                    1. Identifique o nome OFICIAL da carta em INGLÊS (mesmo que a carta na foto esteja em português).
                    2. Responda APENAS com um array JSON com objetos contendo 'card_name' (string) e 'qty' (integer).
                    
                    Exemplo de resposta:
                    [
                        {"card_name": "Sol Ring", "qty": 1},
                        {"card_name": "Command Tower", "qty": 1}
                    ]
                    """
                    
                    response = client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=[image, prompt]
                    )
                    
                    raw_text = response.text.strip()
                    if raw_text.startswith("```json"):
                        raw_text = raw_text.replace("```json", "", 1)
                    if raw_text.startswith("```"):
                        raw_text = raw_text.replace("```", "", 1)
                    if raw_text.endswith("```"):
                        raw_text = raw_text[:-3]
                    
                    cards_data = json.loads(raw_text.strip())
                    
                    st.session_state['detected_cards'] = cards_data
                    st.success(f"✨ {len(cards_data)} carta(s) identificada(s) com sucesso!")
                    
                except Exception as e:
                    st.error(f"Erro ao analisar imagem: {e}")

# Se já tiver cartas detectadas, exibe a tabela
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

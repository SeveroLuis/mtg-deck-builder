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
            with st.spinner("Analisando a imagem com a IA..."):
                try:
                    genai.configure(api_key=api_key)
                    
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
                    
                    # Lista de modelos candidatos para testar em ordem de prioridade
                    candidate_models = [
                        'gemini-1.5-flash',
                        'gemini-2.0-flash',
                        'gemini-2.5-flash',
                        'gemini-3.6-flash',
                        'gemini-1.5-pro'
                    ]
                    
                    response = None
                    used_model = ""
                    last_error = None
                    
                    # Testa cada modelo sequencialmente até encontrar um que a API aceite
                    for model_name in candidate_models:
                        try:
                            model = genai.GenerativeModel(model_name)
                            response = model.generate_content([prompt, image])
                            used_model = model_name
                            break
                        except Exception as err:
                            last_error = err
                            continue
                    
                    if not response:
                        raise Exception(f"Nenhum modelo aceitou a conexão. Último erro: {last_error}")
                    
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
                    st.success(f"✨ {len(cards_data)} carta(s) identificada(s) com sucesso usando o modelo **{used_model}**!")
                    
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

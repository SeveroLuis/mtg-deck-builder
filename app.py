import streamlit as st

st.set_page_config(page_title="MTG Commander Assistant", page_icon="🃏", layout="wide")

st.title("🃏 MTG Commander Assistant")
st.subheader("Protótipo 0.1 - Teste de Conexão")

st.write("Bem-vindo ao assistente de montagem de decks!")

# Entrada da chave de API
api_key = st.text_input("Cole sua Gemini API Key aqui para testar:", type="password")

if api_key:
    st.success("Chave inserida com sucesso! Próximo passo: integrar a visão de imagem.")

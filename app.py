import json
import requests
import streamlit as st
from PIL import Image
import io
import google.generativeai as genai
from concurrent.futures import ThreadPoolExecutor
from fpdf import FPDF

st.set_page_config(page_title="MTG Commander Assistant", layout="wide")

st.title("MTG Commander Assistant")
st.subheader("Protótipo 0.9.0 - Suporte a Múltiplos Comandantes + Exportação PDF & Relatórios")

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
        "User-Agent": "MTGCommanderAssistant/1.0 (https://github.com)",
        "Accept": "application/json"
    }
    
    encoded_query = requests.utils.quote(f'is:commander name:"{query_term.strip()}"')
    url = f"https://api.scryfall.com/cards/search?q={encoded_query}&order=name"
    
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
        auto_url = f"https://api.scryfall.com/cards/autocomplete?q={requests.utils.quote(query_term.strip())}"
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

# --- GERADOR DE PDF DO RELATÓRIO ---
def generate_pdf_report(title_text, content_text):
    """Gera um PDF limpo e formatado usando FPDF2."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Cabeçalho
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "MTG Commander Assistant - Relatorio", ln=True, align="C")
    pdf.set_font("Helvetica", "I", 10)
    pdf.cell(0, 6, f"Foco: {title_text}", ln=True, align="C")
    pdf.ln(10)
    
    # Corpo do texto
    pdf.set_font("Helvetica", "", 10)
    
    # Limpeza básica de caracteres especiais markdown para compatibilidade com Latin-1
    clean_text = content_text.encode('latin-1', 'replace').decode('latin-1')
    
    for line in clean_text.split('\n'):
        # Substituições simples para formatação no PDF
        line_clean = line.replace('#', '').replace('**', '')
        if line.startswith("### "):
            pdf.ln(4)
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 8, line_clean.replace("### ", ""), ln=True)
            pdf.set_font("Helvetica", "", 10)
        elif line.startswith("- ") or line.startswith("* "):
            pdf.multi_cell(0, 6, "  * " + line_clean[2:])
        else:
            pdf.multi_cell(0, 6, line_clean)
            
    return bytes(pdf.output())

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
        combined_colors.update(c2_data.get("color_identity", []))
        display_name += f" & {c2_data['name']}"
        if c2_data['image_url']:
            images_to_show.append(c2_data['image_url'])
            
    final_color_list = sorted(list(combined_colors))
    
    st.session_state['commander_data'] = {
        "name": display_name,
        "color_identity": final_color_list,
        "found": True
    }
    
    st.sidebar.markdown("---")
    st.sidebar.subheader(f"Deck: {display_name}")
    st.sidebar.caption(f"Identidade de Cores Unificada: {', '.join(final_color_list) if final_color_list else 'Incolor'}")
    for img_url in images_to_show:
        st.sidebar.image(img_url, use_container_width=True)

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

# --- FUNÇÃO AUXILIAR PARA PROCESSAMENTO EM PARALELO ---
def _process_single_card(item, cmd_colors, edhrec_db):
    scry = fetch_scryfall_card(item['card_name'])
    if scry['found']:
        valid = is_color_valid(scry['color_identity'], cmd_colors)
        edh_info = edhrec_db.get(scry['name'].lower(), {})
        
        raw_syn = edh_info.get("synergy_raw", 0)
        has_edh_data = edh_info.get("inclusion") is not None
        
        translated_type = translate_type_line(scry['type_line'])
        
        card_dict = {
            "Carta": scry['name'],
            "Qtd": item['qty'],
            "Tipo": translated_type,
            "Valida": "Sim" if valid else "Fora da Cor",
            "Inclusão EDHREC": edh_info.get("inclusion", "Fora do Top EDHREC"),
            "Sinergia EDHREC": edh_info.get("synergy", "0%"),
            "Categoria EDHREC": edh_info.get("category", "Geral/Outros"),
            "_oracle_text": scry['oracle_text']
        }
        
        is_playable = valid and (has_edh_data or raw_syn > 0)
        return card_dict, is_playable
    return None, False

# --- VALIDAÇÃO E ABAS "DÁ JOGO" VS "FORA DO RADAR" ---
if 'detected_cards' in st.session_state and st.session_state['detected_cards']:
    st.markdown("---")
    st.write("### Triagem da Coleção vs Comandante")
    
    if st.button("Validar Coleção no Scryfall e EDHREC"):
        with st.spinner("Buscando dados em paralelo no EDHREC e Scryfall..."):
            cmd_data = st.session_state.get('commander_data', {})
            cmd_name = cmd_data.get('name', '').split(" & ")[0] # EDHREC busca melhor pelo comandante principal
            cmd_colors = cmd_data.get('color_identity', [])
            
            edhrec_db = fetch_edhrec_full_metrics(cmd_name)
            
            playable_cards = []
            junk_cards = []
            
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = [
                    executor.submit(_process_single_card, item, cmd_colors, edhrec_db)
                    for item in st.session_state['detected_cards']
                ]
                for future in futures:
                    card_dict, is_playable = future.result()
                    if card_dict:
                        if is_playable:
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
        
        def clean_display_list(card_list):
            return [
                {k: v for k, v in c.items() if not k.startswith("_")}
                for c in card_list
            ]

        with tab1:
            st.markdown("**Cartas com sinergia ou presença confirmada no EDHREC para este comandante:**")
            if st.session_state['playable_cards']:
                st.dataframe(clean_display_list(st.session_state['playable_cards']), use_container_width=True)
            else:
                st.info("Nenhuma carta com sinergia estatística direta encontrada.")
                
        with tab2:
            st.markdown("**Cartas que cabem na cor, mas não possuem destaque nos dados do EDHREC:**")
            if st.session_state['junk_cards']:
                st.dataframe(clean_display_list(st.session_state['junk_cards']), use_container_width=True)
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
                            f"- {c['Carta']} ({c['Tipo']}) | Categoria: {c['Categoria EDHREC']} | Sinergia EDHREC: {c['Sinergia EDHREC']} | Texto: {c.get('_oracle_text', '')[:80]}"
                            for c in valid_playables
                        ])
                        
                        prompt = f"""
                        Você é um analista estatístico de MTG Commander. Seja EXTREMAMENTE OBJETIVO, CIRÚRGICO e DIRETO. Sem introduções, saudações ou dicas de deckbuilding geral.

                        Comandante(s): {cmd_name}
                        
                        Cartas aproveitáveis da coleção do jogador:
                        {cards_data_prompt}

                        Gere a análise ESTRITAMENTE nas 2 seções abaixo (não adicione nenhuma outra seção):

                        ### Cartas Recomendadas da Coleção (Dados EDHREC)
                        Crie uma tabela Markdown contendo:
                        | Carta | Tipo | Categoria Funcional | Inclusão (%) [Fonte: EDHREC] | Sinergia (%) [Fonte: EDHREC] | Função no Deck |

                        ### Matriz de Sinergias Cruzadas do Fichário (Carta-com-Carta)
                        Analise especificamente como as cartas escaneadas do jogador interagem ENTRE SI e com o(s) comandante(s).
                        Liste apenas duplas concretas de cartas presentes na coleção do jogador (ex: Carta A + Carta B).
                        Use bullet points curtos:
                        - **[Carta A] + [Carta B]**: [Explicação cirúrgica de no máximo 10 palavras da interação direta].
                        """
                        
                        res_text = call_gemini_api(api_key, prompt)
                        st.session_state['last_synergy_analysis'] = res_text
                        st.markdown(res_text)
                        
                        st.markdown("### Exportar Lista para Deckbuilder:")
                        all_valid = valid_playables + [c for c in st.session_state['junk_cards'] if c['Valida'] == "Sim"]
                        export_text = f"1 {cmd_name.split(' & ')[0]}\n" + "\n".join([f"1 {c['Carta']}" for c in all_valid])
                        st.text_area("Copiar para Moxfield / ManaBox / Archidekt:", value=export_text, height=140)
                    
                except Exception as e:
                    st.error(f"Erro no processamento: {e}")

        # Botão de Exportar Relatório de Sinergias em PDF
        if 'last_synergy_analysis' in st.session_state:
            pdf_bytes = generate_pdf_report("Analise de Sinergias Cruzadas", st.session_state['last_synergy_analysis'])
            st.download_button(
                label="📥 Baixar Relatório de Sinergias (PDF)",
                data=pdf_bytes,
                file_name="mtg_sinergias_fichario.pdf",
                mime="application/pdf"
            )

        # --- MÓDULO DE UPGRADE DE DECK PRONTO vs FICHÁRIO ---
        st.markdown("---")
        st.write("### Módulo de Upgrade: Deck Pronto vs Fichário")
        st.markdown("Já tem um deck montado? Cole a lista dele abaixo para descobrir **quais cartas do seu fichário sobem de nível o seu deck atual**.")
        
        user_decklist = st.text_area(
            "Cole a sua lista atual de 100 cartas (Formato: 1 Nome da Carta):",
            placeholder="1 Sol Ring\n1 Command Tower\n1 Cultivate\n1 Molt Tender...",
            height=200
        )
        
        if st.button("Analisar Upgrades do Fichário para o Deck", type="primary"):
            if not user_decklist.strip():
                st.warning("Por favor, cole a lista do seu deck antes de executar a análise de upgrade.")
            else:
                with st.spinner("Cruzando 100 cartas do seu deck com as cartas do fichário..."):
                    try:
                        cmd_name = st.session_state.get('commander_data', {}).get('name', 'Comandante')
                        valid_playables = [c for c in st.session_state['playable_cards'] if c['Valida'] == "Sim"]
                        
                        binder_summary = "\n".join([
                            f"- {c['Carta']} ({c['Tipo']}) | Sinergia: {c['Sinergia EDHREC']}"
                            for c in valid_playables
                        ])
                        
                        prompt = f"""
                        Você é um especialista em otimização e upgrade de decks de MTG Commander.
                        Analise o confronto entre a Lista de Deck Atual do jogador e as Cartas Escaneadas do Fichário.

                        Comandante(s): {cmd_name}

                        LISTA DO DECK ATUAL DO JOGADOR:
                        {user_decklist.strip()}

                        CARTAS DISPONÍVEIS NO FICHÁRIO DO JOGADOR:
                        {binder_summary}

                        Forneça um relatório CIRÚRGICO, DIRETO e OBJETIVO com as seguintes seções (e nada mais):

                        ### Sugestões de Trocas Diretas (Upgrades Claros)
                        Para cada carta do fichário que seja estritamente melhor ou mais sinérgica do que algo no deck:
                        - **Entra (Fichário):** [Nome da Carta do Fichário]  
                          **Sai (Deck):** [Nome da Carta a ser Removida]  
                          **Motivo:** [Explicar a vantagem em no máximo 12 palavras].

                        ### Novas Sinergias Triplas Criadas (Fichário + Deck + Comandante)
                        Identifique duplas/combos formados entre uma carta do fichário e cartas que JÁ ESTAVAM no deck:
                        - **[Carta do Fichário] + [Carta do Deck Atual]**: [Explicação cirúrgica do combo ou sinergia].
                        """
                        
                        upgrade_res = call_gemini_api(api_key, prompt)
                        st.session_state['last_upgrade_analysis'] = upgrade_res
                        st.markdown(upgrade_res)
                        
                    except Exception as e:
                        st.error(f"Erro ao processar análise de upgrade: {e}")

        # Botão de Exportar Relatório de Upgrades em PDF
        if 'last_upgrade_analysis' in st.session_state:
            pdf_upgrade_bytes = generate_pdf_report("Relatorio de Upgrade de Deck", st.session_state['last_upgrade_analysis'])
            st.download_button(
                label="📥 Baixar Relatório de Upgrades (PDF)",
                data=pdf_upgrade_bytes,
                file_name="mtg_upgrades_deck.pdf",
                mime="application/pdf"
            )

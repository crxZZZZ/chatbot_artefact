"""Interface de chat. Execute com: python -m streamlit run app.py."""

import streamlit as st

from emporio.agent import ChatAgent, WELCOME
from emporio.config import load_settings
from emporio.llm import OllamaService, OllamaUnavailableError


def main() -> None:
    st.set_page_config(page_title="Empório da Música", page_icon="🎸")
    st.title("Empório da Música")
    st.caption("Sua música começa aqui.")
    st.info("Protótipo em construção. Consultas de produtos, pedidos e políticas estarão disponíveis nas próximas etapas.")

    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": WELCOME}]
    with st.sidebar:
        st.subheader("Atendimento")
        st.caption("O histórico fica apenas nesta sessão e é apagado ao iniciar uma nova conversa.")
        if st.button("Nova conversa", use_container_width=True):
            st.session_state.messages = [{"role": "assistant", "content": WELCOME}]
            st.rerun()

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])

    try:
        agent = ChatAgent(OllamaService(load_settings()))
    except ValueError as exc:
        st.error(f"Configuração inválida: {exc}")
        st.stop()

    prompt = st.chat_input("Digite sua mensagem")
    if not prompt or not prompt.strip():
        return
    user_message = {"role": "user", "content": prompt.strip()}
    with st.chat_message("user"):
        st.write(user_message["content"])
    with st.chat_message("assistant"):
        try:
            with st.spinner("Preparando sua resposta…"):
                answer = agent.reply([*st.session_state.messages, user_message])
        except OllamaUnavailableError as exc:
            st.error(str(exc))
            st.caption("A mensagem não foi adicionada ao histórico. Você pode enviá-la novamente após corrigir o problema.")
            return
        st.write(answer)
    st.session_state.messages.extend([user_message, {"role": "assistant", "content": answer}])


if __name__ == "__main__":
    main()

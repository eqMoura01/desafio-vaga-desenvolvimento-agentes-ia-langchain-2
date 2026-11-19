class MissingModelConfig(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "Defina OPENAI_API_KEY no arquivo .env. "
            "Um endpoint compatível com a API da OpenAI também serve: "
            "use OPENAI_BASE_URL e OPENAI_MODEL."
        )


class DocumentUnreadable(ValueError):
    pass


class NoDocuments(FileNotFoundError):
    pass

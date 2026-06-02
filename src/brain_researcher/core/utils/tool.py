try:
    from langchain.tools import tool
except ModuleNotFoundError:

    def tool(func):
        return func

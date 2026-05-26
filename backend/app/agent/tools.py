"""
Tool definitions and registry for the agentic system.

Tools are functions the AI can call to interact with external systems.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from enum import Enum


class ToolCategory(str, Enum):
    """Categories of tools for organization and access control."""
    SEARCH = "search"
    CALCULATION = "calculation"
    CODE = "code"
    WEB = "web"
    KNOWLEDGE = "knowledge"
    UTILITY = "utility"
    FILE = "file"


@dataclass
class ToolParameter:
    """Definition of a tool parameter."""
    name: str
    type: str  # "string", "number", "boolean", "array", "object"
    description: str
    required: bool = True
    default: Any = None
    enum: Optional[List[str]] = None


@dataclass
class Tool:
    """
    Definition of a tool that the agent can use.

    Tools are the building blocks of agentic behavior - they allow
    the AI to interact with external systems and take actions.
    """
    name: str
    description: str
    category: ToolCategory
    parameters: List[ToolParameter] = field(default_factory=list)
    handler: Optional[Callable] = None
    requires_confirmation: bool = False
    is_async: bool = True

    def to_prompt_format(self) -> str:
        """Format tool for inclusion in system prompt."""
        params_desc = []
        for p in self.parameters:
            req = "(required)" if p.required else "(optional)"
            params_desc.append(f"    - {p.name} ({p.type}, {req}): {p.description}")

        params_str = "\n".join(params_desc) if params_desc else "    (no parameters)"

        return f"""- **{self.name}**: {self.description}
  Parameters:
{params_str}"""

    def to_json_schema(self) -> Dict[str, Any]:
        """Convert tool to JSON schema format for function calling."""
        properties = {}
        required = []

        for p in self.parameters:
            prop = {"type": p.type, "description": p.description}
            if p.enum:
                prop["enum"] = p.enum
            properties[p.name] = prop
            if p.required:
                required.append(p.name)

        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            }
        }


class ToolRegistry:
    """
    Registry for all available tools.

    Manages tool registration, lookup, and formatting for prompts.
    """

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_all(self) -> List[Tool]:
        """Get all registered tools."""
        return list(self._tools.values())

    def get_by_category(self, category: ToolCategory) -> List[Tool]:
        """Get tools by category."""
        return [t for t in self._tools.values() if t.category == category]

    def get_tools_prompt(self, categories: Optional[List[ToolCategory]] = None) -> str:
        """Generate tools description for system prompt."""
        tools = self._tools.values()
        if categories:
            tools = [t for t in tools if t.category in categories]

        if not tools:
            return "No tools available."

        tools_by_category: Dict[ToolCategory, List[Tool]] = {}
        for tool in tools:
            if tool.category not in tools_by_category:
                tools_by_category[tool.category] = []
            tools_by_category[tool.category].append(tool)

        sections = []
        for category, category_tools in tools_by_category.items():
            tool_descs = [t.to_prompt_format() for t in category_tools]
            sections.append(f"### {category.value.title()} Tools\n" + "\n\n".join(tool_descs))

        return "\n\n".join(sections)

    def get_json_schemas(self) -> List[Dict[str, Any]]:
        """Get JSON schemas for all tools (for function calling)."""
        return [t.to_json_schema() for t in self._tools.values()]


# Global tool registry
tool_registry = ToolRegistry()


# ============================================================================
# Built-in Tool Definitions
# ============================================================================

# RAG Search Tool
rag_search_tool = Tool(
    name="rag_search",
    description="Search the knowledge base for relevant information. Use this when you need to find information from uploaded documents.",
    category=ToolCategory.KNOWLEDGE,
    parameters=[
        ToolParameter(
            name="query",
            type="string",
            description="The search query to find relevant documents",
        ),
        ToolParameter(
            name="top_k",
            type="number",
            description="Number of results to return (1-10)",
            required=False,
            default=5,
        ),
    ],
)

# Web Search Tool
web_search_tool = Tool(
    name="web_search",
    description="Search the internet for current information. Use for recent events, facts, or when knowledge base doesn't have the answer.",
    category=ToolCategory.WEB,
    parameters=[
        ToolParameter(
            name="query",
            type="string",
            description="The search query",
        ),
        ToolParameter(
            name="num_results",
            type="number",
            description="Number of results to return (1-10)",
            required=False,
            default=5,
        ),
    ],
)

# URL Reader Tool
read_url_tool = Tool(
    name="read_url",
    description="Fetch and read the content of a URL. Use to get detailed information from a specific webpage.",
    category=ToolCategory.WEB,
    parameters=[
        ToolParameter(
            name="url",
            type="string",
            description="The URL to read",
        ),
    ],
)

# Calculator Tool
calculator_tool = Tool(
    name="calculator",
    description="Perform mathematical calculations. Supports basic arithmetic, scientific functions, and unit conversions.",
    category=ToolCategory.CALCULATION,
    parameters=[
        ToolParameter(
            name="expression",
            type="string",
            description="The mathematical expression to evaluate (e.g., '2 + 2', 'sqrt(16)', '100 * 0.15')",
        ),
    ],
)

# Python REPL Tool
python_repl_tool = Tool(
    name="python_execute",
    description="Execute Python code and return the result. Use for complex calculations, data manipulation, or when calculator is insufficient.",
    category=ToolCategory.CODE,
    requires_confirmation=True,  # Requires user confirmation for safety
    parameters=[
        ToolParameter(
            name="code",
            type="string",
            description="Python code to execute",
        ),
    ],
)

# Current Time Tool
current_time_tool = Tool(
    name="get_current_time",
    description="Get the current date and time. Use when you need to know the current time or date.",
    category=ToolCategory.UTILITY,
    parameters=[
        ToolParameter(
            name="timezone",
            type="string",
            description="Timezone (e.g., 'UTC', 'America/New_York', 'Asia/Tokyo')",
            required=False,
            default="UTC",
        ),
    ],
)

# Weather Tool (placeholder - needs API key)
weather_tool = Tool(
    name="get_weather",
    description="Get current weather information for a location.",
    category=ToolCategory.UTILITY,
    parameters=[
        ToolParameter(
            name="location",
            type="string",
            description="City name or coordinates",
        ),
    ],
)

# File Read Tool (for uploaded files)
file_read_tool = Tool(
    name="read_file",
    description="Read the contents of an uploaded file. Use when you need to examine file contents.",
    category=ToolCategory.FILE,
    parameters=[
        ToolParameter(
            name="file_id",
            type="number",
            description="The ID of the file/attachment to read",
        ),
    ],
)

# Create Task Tool (for breaking down complex tasks)
create_task_tool = Tool(
    name="create_subtask",
    description="Create a subtask to break down a complex task into smaller steps. Use for multi-step problems.",
    category=ToolCategory.UTILITY,
    parameters=[
        ToolParameter(
            name="description",
            type="string",
            description="Description of the subtask to create",
        ),
        ToolParameter(
            name="priority",
            type="number",
            description="Priority of the subtask (1-5, 1 being highest)",
            required=False,
            default=3,
        ),
    ],
)

# Final Answer Tool (to signal completion)
final_answer_tool = Tool(
    name="final_answer",
    description="Provide the final answer to the user's question. Use this when you have gathered enough information to answer.",
    category=ToolCategory.UTILITY,
    parameters=[
        ToolParameter(
            name="answer",
            type="string",
            description="The final answer to present to the user",
        ),
        ToolParameter(
            name="sources",
            type="array",
            description="List of sources used to generate the answer",
            required=False,
        ),
    ],
)

# Yahoo Finance Tool
yahoo_finance_tool = Tool(
    name="yahoo_finance",
    description="Get stock market and currency data from Yahoo Finance. Use for stock prices, company info, historical data, financial metrics, and exchange rates.",
    category=ToolCategory.WEB,
    parameters=[
        ToolParameter(
            name="symbol",
            type="string",
            description="Stock ticker or currency pair (e.g., 'AAPL', 'GOOGL', 'BBRI.JK' for Indonesian stocks, 'IDR=X' for USD/IDR rate, 'EUR=X' for USD/EUR)",
        ),
        ToolParameter(
            name="action",
            type="string",
            description="Type of data to retrieve",
            required=False,
            default="quote",
            enum=["quote", "info", "history", "financials", "news"],
        ),
        ToolParameter(
            name="period",
            type="string",
            description="Time period for historical data (e.g., '1d', '5d', '1mo', '3mo', '1y')",
            required=False,
            default="1mo",
        ),
    ],
)


# File Generation Tool
generate_file_tool = Tool(
    name="generate_file",
    description=(
        "Generate a downloadable file (CSV, Excel, Word, PowerPoint, or PDF) from structured content. "
        "Use this when the user asks to create a report, spreadsheet, presentation, or document to download. "
        "The content parameter must be a JSON string with this structure:\n"
        '{\n'
        '  "title": "Document title",\n'
        '  "sections": [\n'
        '    {\n'
        '      "heading": "Section heading",\n'
        '      "level": 1,\n'
        '      "content": "Paragraph text",\n'
        '      "bullets": ["Point 1", "Point 2"],\n'
        '      "table": {"headers": ["Col1", "Col2"], "rows": [["A", 1], ["B", 2]]}\n'
        '    }\n'
        '  ],\n'
        '  "sheets": [{"name": "Sheet1", "headers": ["Col","Val"], "rows": [[1,2]]}],\n'
        '  "slides": [{"title": "Slide title", "bullets": ["Point 1"]}]\n'
        '}\n'
        "For xlsx/csv use 'sheets'. For pptx use 'slides'. For docx/pdf use 'sections'. "
        "After calling this tool, include the download link in your response as: [filename](/api/files/download/{file_id})"
    ),
    category=ToolCategory.FILE,
    parameters=[
        ToolParameter(
            name="format",
            type="string",
            description="File format to generate",
            enum=["csv", "xlsx", "docx", "pptx", "pdf"],
        ),
        ToolParameter(
            name="filename",
            type="string",
            description="Base filename without extension (e.g. 'sales_report')",
        ),
        ToolParameter(
            name="content",
            type="string",
            description="JSON string describing the file content (title, sections/sheets/slides)",
        ),
    ],
)


# Register all built-in tools
def register_builtin_tools():
    """Register all built-in tools with the global registry."""
    tools = [
        rag_search_tool,
        web_search_tool,
        read_url_tool,
        calculator_tool,
        python_repl_tool,
        current_time_tool,
        weather_tool,
        file_read_tool,
        create_task_tool,
        final_answer_tool,
        yahoo_finance_tool,
        generate_file_tool,
    ]
    for tool in tools:
        tool_registry.register(tool)


# Auto-register on import
register_builtin_tools()

#
# services/llm_gateway/providers/gemini_provider.py
#
import os
import json
import google.generativeai as genai
from google.api_core import exceptions
from ..provider_base import LLMProvider, CompletionRequest, CompletionResponse, ToolCall

class GeminiProvider(LLMProvider):
    def __init__(self):
        self._api_key = os.environ.get("GEMINI_API_KEY")
        self._model = None

    def get_name(self) -> str:
        return "gemini"

    async def _lazy_init(self):
        if self._model:
            return
        if not self._api_key:
            raise ValueError("Gemini API key is not configured.")
        try:
            genai.configure(api_key=self._api_key)
            self._model = genai.GenerativeModel('gemini-2.0-flash')
        except Exception as e:
            raise RuntimeError(f"Failed to configure Gemini client: {e}")

    def _convert_tools_to_gemini_format(self, tools):
        """Convert OpenAI-style tools to Gemini function declarations."""
        if not tools:
            return None
        
        import google.ai.generativelanguage as glm
        
        gemini_tools = []
        for tool in tools:
            if tool.get("type") == "function":
                func = tool.get("function", {})
                params = func.get("parameters", {})
                
                # Convert parameters to Gemini schema format
                gemini_params = self._convert_parameters_to_gemini_schema(params)
                
                gemini_func = glm.FunctionDeclaration(
                    name=func.get("name"),
                    description=func.get("description", ""),
                    parameters=gemini_params
                )
                gemini_tools.append(gemini_func)
        
        if gemini_tools:
            return glm.Tool(function_declarations=gemini_tools)
        return None
    
    def _convert_parameters_to_gemini_schema(self, params):
        """Convert OpenAI-style parameters to Gemini schema."""
        import google.ai.generativelanguage as glm
        
        # Map type strings to Gemini Type enum
        type_map = {
            "string": glm.Type.STRING,
            "number": glm.Type.NUMBER,
            "integer": glm.Type.INTEGER,
            "boolean": glm.Type.BOOLEAN,
            "array": glm.Type.ARRAY,
            "object": glm.Type.OBJECT
        }
        
        properties = {}
        for prop_name, prop_def in params.get("properties", {}).items():
            prop_type = type_map.get(prop_def.get("type", "string"), glm.Type.STRING)
            properties[prop_name] = glm.Schema(
                type=prop_type,
                description=prop_def.get("description", "")
            )
        
        return glm.Schema(
            type=glm.Type.OBJECT,
            properties=properties,
            required=params.get("required", [])
        )

    def _parse_gemini_response(self, response):
        """Parse Gemini response for text or function calls."""
        content = None
        tool_calls = []
        
        # Check if response has function calls
        if hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                for part in candidate.content.parts:
                    # Text response
                    if hasattr(part, 'text') and part.text:
                        content = part.text
                    # Function call
                    elif hasattr(part, 'function_call'):
                        fc = part.function_call
                        tool_calls.append(ToolCall(
                            id=f"call_{fc.name}",
                            type="function",
                            function={
                                "name": fc.name,
                                "arguments": json.dumps(dict(fc.args)) if fc.args else "{}"
                            }
                        ))
        
        # Fallback to simple text extraction
        if content is None and not tool_calls:
            content = response.text if hasattr(response, 'text') else ""
        
        return content, tool_calls

    async def is_available(self) -> bool:
        return bool(self._api_key)

    async def get_completion(self, request: CompletionRequest) -> CompletionResponse:
        await self._lazy_init()
        if not self._model:
            raise RuntimeError("Gemini model is not initialized.")
        
        gemini_messages = [{"role": "user", "parts": [msg.content]} for msg in request.messages]
        
        # Convert tools to Gemini format
        gemini_tools = self._convert_tools_to_gemini_format(request.tools)
        
        # Debug logging
        import logging
        logger = logging.getLogger("gemini_provider")
        logger.info(f"🔧 Tools received: {len(request.tools) if request.tools else 0}")
        logger.info(f"🔧 Gemini tools: {gemini_tools}")
        
        try:
            # Create generation config
            generation_config = {}
            if request.temperature is not None:
                generation_config["temperature"] = request.temperature
            if request.max_tokens:
                generation_config["max_output_tokens"] = request.max_tokens
            
            # Generate content with or without tools
            if gemini_tools:
                response = await self._model.generate_content_async(
                    gemini_messages,
                    tools=[gemini_tools],  # Gemini expects a list of Tool objects
                    generation_config=generation_config,
                    stream=False
                )
            else:
                response = await self._model.generate_content_async(
                    gemini_messages,
                    generation_config=generation_config,
                    stream=False
                )
            
            # Parse response
            content, tool_calls = self._parse_gemini_response(response)
            
            return CompletionResponse(
                content=content,
                provider_name=self.get_name(),
                model='gemini-2.0-flash',
                tool_calls=tool_calls if tool_calls else None
            )
        except exceptions.ResourceExhausted as e:
            raise RuntimeError(f"Gemini API rate limit exceeded: {e}")


    async def get_streaming_completion(self, request: CompletionRequest):
        await self._lazy_init()
        if not self._model:
            raise RuntimeError("Gemini model is not initialized.")
        
        gemini_messages = [{"role": "user", "parts": [msg.content]} for msg in request.messages]
        
        # Convert tools to Gemini format
        gemini_tools = self._convert_tools_to_gemini_format(request.tools)
        
        try:
            # Create generation config
            generation_config = {}
            if request.temperature is not None:
                generation_config["temperature"] = request.temperature
            if request.max_tokens:
                generation_config["max_output_tokens"] = request.max_tokens
            
            # Generate streaming content with or without tools
            if gemini_tools:
                response = await self._model.generate_content_async(
                    gemini_messages,
                    tools=[gemini_tools],  # Gemini expects a list of Tool objects
                    generation_config=generation_config,
                    stream=True
                )
            else:
                response = await self._model.generate_content_async(
                    gemini_messages,
                    generation_config=generation_config,
                    stream=True
                )
            
            async for chunk in response:
                if chunk.text:
                    yield chunk.text
        except exceptions.ResourceExhausted as e:
            yield f"Error: Gemini API rate limit exceeded. {e}"

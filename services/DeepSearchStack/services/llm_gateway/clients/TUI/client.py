#!/usr/bin/env python3
"""
Terminal User Interface (TUI) Client for LLM Gateway
Provides an interactive terminal interface to interact with the LLM Gateway API
"""

import asyncio
import json
import os
from typing import Dict, Optional
import httpx
import rich
from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.prompt import Prompt

from textual import on, events
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    LoadingIndicator,
    Select,
    Static,
    TextArea,
)
from textual.binding import Binding


class SettingsScreen(Static):
    """Settings screen for configuring LLM Gateway connection parameters"""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.gateway_url = os.environ.get("LLM_GATEWAY_URL", "http://localhost:8080")
        self.default_model = os.environ.get("LLM_DEFAULT_MODEL", "llama-3.1-8b-instant")
        self.default_provider = os.environ.get("LLM_DEFAULT_PROVIDER", "")
        self.default_temperature = float(os.environ.get("LLM_TEMPERATURE", "0.7"))
        
    def compose(self) -> ComposeResult:
        yield Label("Settings", classes="title")
        
        # Gateway URL
        yield Label("Gateway URL:", classes="setting-label")
        self.url_input = Input(
            placeholder="Enter LLM Gateway URL",
            value=self.gateway_url,
            id="gateway-url"
        )
        yield self.url_input
        
        # Model Selection
        yield Label("Model:", classes="setting-label")
        self.model_input = Input(
            placeholder="Enter model name",
            value=self.default_model,
            id="model-name"
        )
        yield self.model_input
        
        # Provider Selection
        yield Label("Provider:", classes="setting-label")
        self.provider_input = Input(
            placeholder="Enter provider (optional)",
            value=self.default_provider,
            id="provider-name"
        )
        yield self.provider_input
        
        # Temperature
        yield Label("Temperature (0.0-2.0):", classes="setting-label")
        self.temperature_input = Input(
            placeholder="Enter temperature (0.0-2.0)",
            value=str(self.default_temperature),
            id="temperature"
        )
        yield self.temperature_input
        
        # Save button
        yield Horizontal(
            Button("Save", variant="success", id="save-settings"),
            Button("Cancel", variant="error", id="cancel-settings"),
            classes="button-row"
        )


class ChatMessage(Static):
    """Display a single chat message"""
    
    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content
        super().__init__(classes=f"message message-{role}")
        
    def compose(self) -> ComposeResult:
        role_text = Text(self.role.upper(), style="bold")
        content_text = Text(self.content)
        
        if self.role == "user":
            role_text.stylize("blue")
        elif self.role == "assistant":
            role_text.stylize("green")
        else:
            role_text.stylize("yellow")
            
        yield Static(role_text)
        yield Static(content_text, classes="message-content")


class ChatContainer(VerticalScroll):
    """Container for chat messages"""
    
    def __init__(self):
        super().__init__(classes="chat-container")
        
    def add_message(self, role: str, content: str):
        """Add a new message to the chat"""
        message = ChatMessage(role, content)
        self.mount(message)
        self.scroll_end(animate=False)


class LLMGatewayTUI(App):
    """Main TUI application for LLM Gateway"""
    
    BINDINGS = [
        Binding("ctrl+d", "toggle_dark", "Toggle Dark Mode"),
        Binding("ctrl+s", "show_settings", "Settings"),
        Binding("ctrl+c", "quit", "Quit"),
    ]
    
    CSS = """
    Screen {
        layout: vertical;
    }
    
    #main-container {
        height: 1fr;
    }
    
    #input-container {
        dock: bottom;
        height: 1fr;
        width: 100%;
        layout: horizontal;
        border-top: solid $primary;
    }
    
    #message-input {
        height: 1fr;
        width: 1fr;
    }
    
    #send-button {
        width: 16;
        height: 1fr;
        margin: 1 1 1 0;
    }
    
    #settings-screen {
        height: 1fr;
        width: 1fr;
        offset-x: 5;
        offset-y: 2;
        border: solid $primary;
        background: $surface;
        padding: 1;
    }
    
    .title {
        text-style: bold;
        text-align: center;
        margin: 1 0;
    }
    
    .setting-label {
        margin-top: 1;
        text-style: bold;
    }
    
    .button-row {
        margin-top: 1;
        align-horizontal: center;
    }
    
    .chat-container {
        height: 1fr;
        width: 1fr;
        margin: 1 1 0 1;
    }
    
    .message {
        margin: 1 0;
        padding: 1;
        border-left: solid $accent 2;
    }
    
    .message-user {
        background: $primary 10%;
    }
    
    .message-assistant {
        background: $success 10%;
    }
    
    .message-content {
        margin-top: 1;
    }
    
    .loading-indicator {
        height: 1fr;
        align: center middle;
    }
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.gateway_url = os.environ.get("LLM_GATEWAY_URL", "http://localhost:8080")
        self.default_model = os.environ.get("LLM_DEFAULT_MODEL", "llama-3.1-8b-instant")
        self.default_provider = os.environ.get("LLM_DEFAULT_PROVIDER", "")
        self.default_temperature = float(os.environ.get("LLM_TEMPERATURE", "0.7"))
        self.chat_history = []
        
    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        yield Container(
            ChatContainer(id="chat-container"),
            LoadingIndicator(id="loading-indicator", visible=False),
            id="main-container"
        )
        with Horizontal(id="input-container"):
            yield Input(
                placeholder="Type your message here...",
                id="message-input"
            )
            yield Button("Send", variant="primary", id="send-button")
        
        yield Footer()
        
    def on_mount(self) -> None:
        """Called when the app is mounted."""
        # Add welcome message
        chat_container = self.query_one("#chat-container", ChatContainer)
        chat_container.add_message("system", "Welcome to LLM Gateway TUI! Type your message below or press Ctrl+S to configure settings.")
        
    @on(Button.Pressed, "#send-button")
    def send_message(self) -> None:
        """Send the user's message to the LLM Gateway."""
        input_widget = self.query_one("#message-input", Input)
        message = input_widget.value.strip()
        
        if not message:
            return
            
        # Clear the input
        input_widget.value = ""
        
        # Add user message to chat
        chat_container = self.query_one("#chat-container", ChatContainer)
        chat_container.add_message("user", message)
        
        # Add to chat history
        self.chat_history.append({"role": "user", "content": message})
        
        # Show loading indicator
        loading = self.query_one("#loading-indicator", LoadingIndicator)
        loading.visible = True
        
        # Send the request
        self.call_later(self._make_api_request, message)
        
    @on(Input.Submitted, "#message-input")
    def handle_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in the input field."""
        if event.input.value.strip():
            self.send_message()
            
    @on(Button.Pressed, "#save-settings")
    def save_settings(self) -> None:
        """Save settings and return to main screen."""
        settings_screen = self.query_one("#settings-screen", SettingsScreen)
        
        # Get values from the settings screen
        new_gateway_url = settings_screen.url_input.value.strip()
        new_model = settings_screen.model_input.value.strip()
        new_provider = settings_screen.provider_input.value.strip()
        new_temperature = settings_screen.temperature_input.value.strip()
        
        # Validate temperature
        try:
            temp_float = float(new_temperature)
            if not (0.0 <= temp_float <= 2.0):
                self.notify("Temperature must be between 0.0 and 2.0", severity="error")
                return
        except ValueError:
            self.notify("Temperature must be a valid number", severity="error")
            return
        
        # Update settings
        self.gateway_url = new_gateway_url
        self.default_model = new_model
        self.default_provider = new_provider
        self.default_temperature = temp_float
        
        # Hide settings screen
        settings_screen.styles.visibility = "hidden"
        self.notify("Settings saved successfully!", severity="success")
        
    @on(Button.Pressed, "#cancel-settings")
    def cancel_settings(self) -> None:
        """Cancel settings and return to main screen."""
        settings_screen = self.query_one("#settings-screen", SettingsScreen)
        settings_screen.styles.visibility = "hidden"
        
    def action_show_settings(self) -> None:
        """Show the settings screen."""
        # Create settings screen if it doesn't exist
        if not self.query("#settings-screen").first():
            self.mount(SettingsScreen(id="settings-screen"))
        
        # Show settings screen
        settings_screen = self.query_one("#settings-screen", SettingsScreen)
        settings_screen.styles.visibility = "visible"
        
    async def _make_api_request(self, message: str) -> None:
        """Make API request to LLM Gateway."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                payload = {
                    "messages": self.chat_history,
                    "model": self.default_model,
                    "temperature": self.default_temperature,
                    "stream": False  # For now, disable streaming for simplicity
                }
                
                if self.default_provider:
                    payload["provider"] = self.default_provider
                
                response = await client.post(
                    f"{self.gateway_url}/v1/completions",
                    json=payload,
                    headers={"Content-Type": "application/json"}
                )
                
                if response.status_code != 200:
                    error_msg = f"API Error: {response.status_code} - {response.text}"
                    self._add_assistant_message(error_msg)
                    return
                
                data = response.json()
                content = data.get("content", "No content in response")
                
                # Add to chat history
                self.chat_history.append({"role": "assistant", "content": content})
                
                # Update UI with the response
                self._add_assistant_message(content)
                
        except httpx.RequestError as e:
            error_msg = f"Request Error: {str(e)}"
            self._add_assistant_message(error_msg)
        except httpx.TimeoutException:
            error_msg = "Request Timeout: The server took too long to respond"
            self._add_assistant_message(error_msg)
        except json.JSONDecodeError:
            error_msg = "Error: Invalid JSON response from server"
            self._add_assistant_message(error_msg)
        except Exception as e:
            error_msg = f"Unexpected Error: {str(e)}"
            self._add_assistant_message(error_msg)
    
    def _add_assistant_message(self, content: str) -> None:
        """Add an assistant message to the chat."""
        # Hide loading indicator
        loading = self.query_one("#loading-indicator", LoadingIndicator)
        loading.visible = False
        
        # Add message to chat
        chat_container = self.query_one("#chat-container", ChatContainer)
        chat_container.add_message("assistant", content)
        
    def action_toggle_dark(self) -> None:
        """Toggle dark mode."""
        self.dark = not self.dark


def main():
    """Main entry point for the TUI client."""
    app = LLMGatewayTUI()
    app.run()


if __name__ == "__main__":
    main()
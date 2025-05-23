"""Config flow for VoIP integration."""

from __future__ import annotations

from typing import Any

from voip_utils import SIP_PORT
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .const import CONF_SIP_PORT, CONF_SIP_USER, DOMAIN


class VoIPConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for VoIP integration."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is None:
            return self.async_show_form(
                step_id="user",
            )

        return self.async_create_entry(
            title="Voice over IP",
            data=user_input,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlow:
        """Create the options flow."""
        return VoipOptionsFlowHandler()


class VoipOptionsFlowHandler(OptionsFlow):
    """Handle VoIP options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            if CONF_SIP_USER in user_input and not user_input[CONF_SIP_USER]:
                del user_input[CONF_SIP_USER]
            self.hass.config_entries.async_update_entry(
                self.config_entry, options=user_input
            )
            return self.async_create_entry(
                title="",
                data=user_input,
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SIP_PORT,
                        default=self.config_entry.options.get(
                            CONF_SIP_PORT,
                            SIP_PORT,
                        ),
                    ): cv.port,
                    vol.Optional(
                        CONF_SIP_USER,
                        description={
                            "suggested_value": self.config_entry.options.get(
                                CONF_SIP_USER, None
                            )
                        },
                    ): vol.Any(None, cv.string),
                }
            ),
        )

"""`aiba run` subcommand — execute the agent with a prompt."""


from src.cli.banner import print_startup_banner
from src.cli.wizard import run_wizard


def run_command(
    prompt: str | None = None,
    mode: str = "agent",
    template: str = "default",
    effort: str = "balanced",
    sub_agents: int = 5,
    interactive: bool = False,
) -> None:
    """Execute an AIBA agent run.

    If PROMPT is provided, runs non-interactively using the given options.
    If PROMPT is omitted, launches the interactive setup wizard.
    """
    if prompt and not interactive:
        _non_interactive_run(prompt, mode, template, effort, sub_agents)
    else:
        # No prompt or --interactive flag → launch wizard (wizard prints its own banner)
        run_wizard()


def _non_interactive_run(
    prompt: str,
    mode: str = "agent",
    template_name: str = "default",
    effort: str = "balanced",
    sub_agent_count: int = 5,
) -> None:
    """Run the agent non-interactively with the given parameters."""
    print_startup_banner()

    from src.prompts import EffortMode, get_effort_config, get_template
    from src.utils.settings import AibaSettings

    _settings = AibaSettings()

    template = get_template(template_name)
    effort_mode = EffortMode(effort)
    config = get_effort_config(effort_mode)

    full_prompt = template.generate_prompt(_settings.user_profile, prompt)

    from src.agents.main_agent import run as run_orch
    from src.agents.sub_agent import run as run_agent
    from src.cli.status import AgentStatus
    from src.services import rendering as R

    if mode == "swarm":
        agent_fn = run_orch
        agent_name = "Orchestrator"
    else:
        agent_fn = run_agent
        agent_name = "Agent"

    model_name = _settings.gemini_main_model if mode == "swarm" else _settings.gemini_sub_model

    import typer

    try:
        with AgentStatus(
            agent_name=agent_name, model_name=model_name,
        ):
            result = agent_fn(prompt=full_prompt, effort_mode=effort_mode)

        R.console.print()
        R.divider()
        R.render_markdown(result.output)
        R.divider()
        R.console.print()

        # Enter REPL after completion
        from src.services.repl import run as run_repl

        session_settings: dict = {
            "mode": mode,
            "effort": effort,
            "template_name": template_name,
        }
        if mode == "swarm":
            session_settings["sub_agent_count"] = sub_agent_count

        run_repl(agent_fn, result, config, agent_name, session_settings)

    except Exception as exc:
        R.console.print(R.panel_error("FATAL ERROR", f"{type(exc).__name__}: {exc}"))
        raise typer.Exit(code=1) from exc

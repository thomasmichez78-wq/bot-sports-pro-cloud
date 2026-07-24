from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

from bot_sports_pro.config.settings import AppSettings
from bot_sports_pro.core.logging_setup import configure_logging
from bot_sports_pro.services.football_collection import collect_football_fixtures
from bot_sports_pro.services.football_backtest import run_football_backtest
from bot_sports_pro.services.football_model_comparison import (
    compare_football_models,
)
from bot_sports_pro.services.football_live_history import (
    update_football_live_history,
)
from bot_sports_pro.services.football_live_analysis import (
    analyze_live_football,
)
from bot_sports_pro.services.football_sports_data import collect_football_sports_data
from bot_sports_pro.services.football_training_data import (
    collect_football_training_data,
)
from bot_sports_pro.services.football_value_evaluation import (
    evaluate_live_football_value,
)
from bot_sports_pro.services.health import build_health_report, format_health_report
from bot_sports_pro.services.odds_collection import collect_football_odds
from bot_sports_pro.services.odds_discovery import discover_odds_football
from bot_sports_pro.services.odds_market_analysis import analyze_football_odds_market


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bot Sports Pro")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="Initialiser les dossiers du projet.")
    subparsers.add_parser("status", help="Afficher le diagnostic.")

    collect_parser = subparsers.add_parser(
        "collect-football",
        help="Collecter et normaliser les rencontres de football.",
    )
    collect_parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Première date au format AAAA-MM-JJ (défaut : aujourd'hui).",
    )
    collect_parser.add_argument(
        "--days",
        type=int,
        default=2,
        help="Nombre de jours consécutifs, de 1 à 7 (défaut : 2).",
    )
    discover_parser = subparsers.add_parser(
        "discover-odds-football",
        help="Mesurer la couverture The Odds API sans consommer de crédit de cotes.",
    )
    discover_parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Première date au format AAAA-MM-JJ (défaut : aujourd'hui).",
    )
    discover_parser.add_argument(
        "--days",
        type=int,
        default=2,
        help="Nombre de jours consécutifs, de 1 à 7 (défaut : 2).",
    )
    odds_parser = subparsers.add_parser(
        "collect-odds-football",
        help="Collecter les cotes h2h/1N2 avec plafond de crédits.",
    )
    odds_parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Première date au format AAAA-MM-JJ (défaut : aujourd'hui).",
    )
    odds_parser.add_argument(
        "--days",
        type=int,
        default=2,
        help="Nombre de jours consécutifs, de 1 à 7 (défaut : 2).",
    )
    odds_parser.add_argument(
        "--max-credits",
        type=int,
        default=12,
        help="Plafond dur de crédits pour cette exécution (défaut : 12).",
    )
    market_parser = subparsers.add_parser(
        "analyze-odds-football",
        help="Comparer Winamax France à la référence Pinnacle corrigée de marge.",
    )
    market_parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Première date au format AAAA-MM-JJ (défaut : aujourd'hui).",
    )
    market_parser.add_argument(
        "--days",
        type=int,
        default=2,
        help="Nombre de jours consécutifs, de 1 à 7 (défaut : 2).",
    )
    sports_data_parser = subparsers.add_parser(
        "collect-football-data",
        help="Collecter historique et classements avec cache quotidien.",
    )
    sports_data_parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Première date au format AAAA-MM-JJ (défaut : aujourd'hui).",
    )
    sports_data_parser.add_argument(
        "--days",
        type=int,
        default=2,
        help="Nombre de jours consécutifs, de 1 à 7 (défaut : 2).",
    )
    sports_data_parser.add_argument(
        "--history-days",
        type=int,
        default=180,
        help="Profondeur maximale de l'historique, de 30 à 365 jours.",
    )
    sports_data_parser.add_argument(
        "--max-requests",
        type=int,
        default=20,
        help="Plafond dur de requêtes API-Football (défaut : 20).",
    )
    training_parser = subparsers.add_parser(
        "collect-training-data",
        help="Collecter une saison historique pour développement et backtest.",
    )
    training_parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Date du lot réel servant à sélectionner les compétitions.",
    )
    training_parser.add_argument(
        "--days",
        type=int,
        default=2,
        help="Nombre de jours du lot réel, de 1 à 7.",
    )
    training_parser.add_argument(
        "--season",
        type=int,
        default=2024,
        help="Saison historique accessible (défaut : 2024).",
    )
    training_parser.add_argument(
        "--max-requests",
        type=int,
        default=20,
        help="Plafond dur de requêtes API-Football (défaut : 20).",
    )
    backtest_parser = subparsers.add_parser(
        "backtest-football",
        help="Évaluer chronologiquement le premier modèle football.",
    )
    backtest_parser.add_argument(
        "--season",
        type=int,
        default=2024,
        help="Saison historique à évaluer (défaut : 2024).",
    )
    backtest_parser.add_argument(
        "--min-team-matches",
        type=int,
        default=5,
        help="Historique minimal par équipe avant une prédiction (défaut : 5).",
    )
    comparison_parser = subparsers.add_parser(
        "compare-football-models",
        help="Choisir le modèle sur une saison et le valider sur une autre.",
    )
    comparison_parser.add_argument(
        "--development-season",
        type=int,
        default=2023,
        help="Saison utilisée pour choisir les poids (défaut : 2023).",
    )
    comparison_parser.add_argument(
        "--validation-season",
        type=int,
        default=2024,
        help="Saison laissée hors réglage (défaut : 2024).",
    )
    comparison_parser.add_argument(
        "--min-team-matches",
        type=int,
        default=5,
        help="Historique minimal par équipe (défaut : 5).",
    )
    live_history_parser = subparsers.add_parser(
        "update-live-football-history",
        help="Archiver définitivement les résultats football de la veille.",
    )
    live_history_parser.add_argument(
        "--date",
        default=None,
        help="Date à archiver (défaut et seule date autorisée : hier).",
    )
    live_analysis_parser = subparsers.add_parser(
        "analyze-live-football",
        help="Analyser les matchs à venir sans demander de cotes.",
    )
    live_analysis_parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Première date au format AAAA-MM-JJ.",
    )
    live_analysis_parser.add_argument(
        "--days",
        type=int,
        default=2,
        help="Nombre de jours consécutifs, de 1 à 3 (défaut : 2).",
    )
    value_parser = subparsers.add_parser(
        "evaluate-live-football-value",
        help="Évaluer la value Winamax et enregistrer les paris en mode papier.",
    )
    value_parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Première date au format AAAA-MM-JJ.",
    )
    value_parser.add_argument(
        "--days",
        type=int,
        default=2,
        help="Nombre de jours consécutifs, de 1 à 3 (défaut : 2).",
    )
    value_parser.add_argument(
        "--max-credits",
        type=int,
        default=3,
        help="Plafond dur de crédits de cotes (défaut : 3).",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = Path(__file__).resolve().parent
    settings = AppSettings.load(root)
    settings.ensure_directories()
    configure_logging(settings.logs_dir)

    report = build_health_report(settings)

    if args.command in {"init", "status"}:
        print(format_health_report(report))
    if args.command == "init":
        print("\nSocle initialisé. Aucun pronostic n'est produit à cette étape.")
    elif args.command == "backtest-football":
        try:
            command_report = run_football_backtest(
                settings,
                season=args.season,
                min_team_matches=args.min_team_matches,
            )
        except Exception as error:
            print(f"ERREUR : {error}", file=sys.stderr)
            return 1
        print(command_report.to_text())
    elif args.command == "compare-football-models":
        try:
            command_report = compare_football_models(
                settings,
                development_season=args.development_season,
                validation_season=args.validation_season,
                min_team_matches=args.min_team_matches,
            )
        except Exception as error:
            print(f"ERREUR : {error}", file=sys.stderr)
            return 1
        print(command_report.to_text())
    elif args.command == "update-live-football-history":
        try:
            requested_date = (
                date.fromisoformat(args.date)
                if args.date is not None
                else None
            )
            command_report = update_football_live_history(
                settings,
                requested_date=requested_date,
            )
        except ValueError as error:
            print(f"ERREUR : {error}", file=sys.stderr)
            return 2
        except Exception as error:
            print(f"ERREUR : {error}", file=sys.stderr)
            return 1
        print(command_report.to_text())
    elif args.command == "analyze-live-football":
        if not 1 <= args.days <= 3:
            print(
                "ERREUR : --days doit être compris entre 1 et 3.",
                file=sys.stderr,
            )
            return 2
        try:
            start_date = date.fromisoformat(args.date)
            dates = tuple(
                start_date + timedelta(days=offset)
                for offset in range(args.days)
            )
            command_report = analyze_live_football(settings, dates)
        except ValueError as error:
            print(f"ERREUR : {error}", file=sys.stderr)
            return 2
        except Exception as error:
            print(f"ERREUR : {error}", file=sys.stderr)
            return 1
        print(command_report.to_text())
    elif args.command == "evaluate-live-football-value":
        if not 1 <= args.days <= 3:
            print(
                "ERREUR : --days doit être compris entre 1 et 3.",
                file=sys.stderr,
            )
            return 2
        try:
            start_date = date.fromisoformat(args.date)
            dates = tuple(
                start_date + timedelta(days=offset)
                for offset in range(args.days)
            )
            command_report = evaluate_live_football_value(
                settings,
                dates,
                max_credits=args.max_credits,
            )
        except ValueError as error:
            print(f"ERREUR : {error}", file=sys.stderr)
            return 2
        except Exception as error:
            print(f"ERREUR : {error}", file=sys.stderr)
            return 1
        print(command_report.to_text())
    elif args.command in {
        "collect-football",
        "discover-odds-football",
        "collect-odds-football",
        "analyze-odds-football",
        "collect-football-data",
        "collect-training-data",
    }:
        if not 1 <= args.days <= 7:
            print("ERREUR : --days doit être compris entre 1 et 7.", file=sys.stderr)
            return 2
        try:
            start_date = date.fromisoformat(args.date)
        except ValueError:
            print("ERREUR : --date doit respecter le format AAAA-MM-JJ.", file=sys.stderr)
            return 2

        dates = tuple(start_date + timedelta(days=offset) for offset in range(args.days))
        try:
            if args.command == "collect-football":
                command_report = collect_football_fixtures(settings, dates)
            elif args.command == "discover-odds-football":
                command_report = discover_odds_football(settings, dates)
            elif args.command == "collect-odds-football":
                command_report = collect_football_odds(
                    settings,
                    dates,
                    max_credits=args.max_credits,
                )
            else:
                if args.command == "analyze-odds-football":
                    command_report = analyze_football_odds_market(settings, dates)
                else:
                    if args.command == "collect-football-data":
                        command_report = collect_football_sports_data(
                            settings,
                            dates,
                            history_days=args.history_days,
                            max_requests=args.max_requests,
                        )
                    else:
                        command_report = collect_football_training_data(
                            settings,
                            dates,
                            season=args.season,
                            max_requests=args.max_requests,
                        )
        except Exception as error:
            print(f"ERREUR : {error}", file=sys.stderr)
            return 1
        print(command_report.to_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())

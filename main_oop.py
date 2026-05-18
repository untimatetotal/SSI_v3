import argparse
import sys
from models import Config, ResumeScreener

print("=== โปรแกรมเริ่มทำงาน ===")
print(f"Python version: {sys.version}")

def main():
    print("=== เข้า main() ===")
    parser = argparse.ArgumentParser(description="Resume Screener (OOP)")
    parser.add_argument("--jd",        required=True)
    parser.add_argument("--resumes",   required=True, nargs="+")
    parser.add_argument("--output",    default="results.json")
    parser.add_argument("--min-score", type=int, default=0)
    parser.add_argument("--pass-only", action="store_true")
    parser.add_argument("--required",  nargs="*", default=[])
    parser.add_argument("--bonus",     nargs="*", default=[])
    args = parser.parse_args()

    print(f"JD: {args.jd}")
    print(f"Resumes: {args.resumes}")

    config   = Config(required_keywords=args.required,
                      bonus_keywords=args.bonus)
    screener = ResumeScreener(config=config)
    results  = screener.screen(
        jd_path=args.jd,
        resume_paths=args.resumes,
        min_score=args.min_score,
        pass_only=args.pass_only,
    )
    screener.print_results(results)
    screener.save_json(results, output=args.output)

if __name__ == "__main__":
    main()
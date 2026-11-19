"""G0 offline BF16 inference check; streaming and LoRA gates remain separate."""
import argparse
import json
from pathlib import Path


def main():
    from vllm import LLM, SamplingParams
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    llm = LLM(model=args.model, dtype="bfloat16", max_model_len=512,
              gpu_memory_utilization=0.5, enforce_eager=True,
              max_num_seqs=4, enable_prefix_caching=False)
    results = llm.generate(["Continue the sequence: one, two, three,"],
                           SamplingParams(temperature=0, max_tokens=16))
    rows = [{"prompt": r.prompt, "text": r.outputs[0].text,
             "token_ids": list(r.outputs[0].token_ids)} for r in results]
    if not rows or not rows[0]["token_ids"]:
        raise RuntimeError("No output tokens")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"model": args.model, "dtype": "bfloat16",
                           "offline_passed": True, "streaming_verified": False,
                           "lora_verified": False, "outputs": rows}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

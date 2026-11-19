"""Create deterministic Qwen3 LoRA fixtures for binding checks."""

import argparse
import hashlib
import json
from pathlib import Path

import torch
from safetensors.torch import save_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads((args.model / "config.json").read_text(encoding="utf-8"))
    if config["model_type"] != "qwen3":
        parser.error("Only Qwen3 is supported")
    rank = 8
    width = config["num_attention_heads"] * config["head_dim"]
    hidden = config["hidden_size"]
    layers = range(config["num_hidden_layers"] - 4, config["num_hidden_layers"])
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {"rank": rank, "alpha": rank, "module": "o_proj",
                "layers": list(layers), "stddev": 0.12, "adapters": {}}
    for name, seed in zip("ABCD", range(4101, 4105)):
        directory = args.output / name
        directory.mkdir(exist_ok=True)
        rng = torch.Generator().manual_seed(seed)
        tensors = {}
        for layer in layers:
            prefix = f"base_model.model.model.layers.{layer}.self_attn.o_proj"
            for suffix, shape in (("A", (rank, width)), ("B", (hidden, rank))):
                tensors[f"{prefix}.lora_{suffix}.weight"] = (
                    torch.randn(shape, generator=rng) * manifest["stddev"]
                ).to(torch.bfloat16)
        weights = directory / "adapter_model.safetensors"
        save_file(tensors, weights, metadata={"format": "pt"})
        adapter_config = {"base_model_name_or_path": "Qwen/Qwen3-0.6B",
                          "peft_type": "LORA", "task_type": "CAUSAL_LM", "r": rank,
                          "lora_alpha": rank, "target_modules": ["o_proj"],
                          "bias": "none", "lora_dropout": 0.0}
        config_path = directory / "adapter_config.json"
        config_path.write_text(json.dumps(adapter_config, indent=2) + "\n", encoding="utf-8")
        manifest["adapters"][name] = {"seed": seed,
            "weights_sha256": hashlib.sha256(weights.read_bytes()).hexdigest(),
            "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest()}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

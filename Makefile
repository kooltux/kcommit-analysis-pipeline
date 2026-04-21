CFG ?= ./configs/local-example-arm32-cyber.json
all:
	./run_pipeline.sh $(CFG)
collect:
	python3 01_collect_commits.py --config $(CFG)
context:
	python3 02_collect_build_context.py --config $(CFG)
product-map:
	python3 03_build_product_map.py --config $(CFG)
enrich:
	python3 04_enrich_commits.py --config $(CFG)
score:
	python3 05_score_commits.py --config $(CFG)
report:
	python3 06_report_commits.py --config $(CFG)

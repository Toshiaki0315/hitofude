.DEFAULT_GOAL := help
.PHONY: help setup run test test-fast cov bench fmt lint check clean ocr-tool \
	app app-lite all dist dmg _bundle icon run-lite

UV := uv

help: ## このヘルプを表示
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## 仮想環境と依存をセットアップ
	$(UV) sync --all-groups

OCR_TOOL := hitofude/resources/bin/hitofude-ocr

ocr-tool: $(OCR_TOOL) ## 文字の読み取りの道具を作る（ADR-0027）

# **swiftc が無ければ作らない。** アプリは今まで通り動き、macOS 側の
# 読み取りだけが使えない（手元の LLM には切り替えられる）
$(OCR_TOOL): tools/ocr/ocr.swift
	@if command -v swiftc >/dev/null 2>&1; then \
		mkdir -p $(dir $@) && swiftc -O $< -o $@ && echo "作った: $@"; \
	else \
		echo "swiftc が無いので飛ばす（macOS の読み取りは使えません）"; \
	fi

run: ocr-tool ## アプリを起動
	$(UV) run python -m hitofude

test: ## テスト全件
	$(UV) run pytest

test-fast: ## GUI/slow を除いた高速テスト
	$(UV) run pytest -m "not gui and not slow"

cov: ## カバレッジ計測（core は 90% 必須）
	$(UV) run pytest --cov --cov-report=term-missing -o faulthandler_timeout=300

bench: ## 性能の受け入れ基準（CLAUDE.md §7）を実測
	$(UV) run python scripts/bench.py


fmt: ## Lint 自動修正 + フォーマット
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

lint: ## Lint とフォーマットの検査のみ
	$(UV) run ruff check .
	$(UV) run ruff format --check .

check: lint test ## コミット前の全チェック

clean: ## キャッシュと成果物を削除
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov build dist
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

# py2app は zlib が共有モジュールの Python を要求する（uv 同梱の CPython は
# 静的リンクで zlib.__file__ を持たず、ビルド途中で落ちる）。
# 開発用の venv はそのままに、ビルドだけ別インタプリタで走らせる。
BUILD_PYTHON ?= /opt/homebrew/bin/python3.13

# **組み立ての中身はここ 1 か所だけ。** app / app-lite / all が呼ぶ。
# 通常版と軽量版の違いは合図（HITOFUDE_LITE）と削り方と名前だけなので、
# 写しを作ると片方を直し忘れる
_bundle:
	rm -rf build
	$(if $(LITE),HITOFUDE_LITE=1) $(UV) run --python $(BUILD_PYTHON) --with py2app --with setuptools python setup.py py2app
	$(UV) run python scripts/prune_bundle.py $(if $(LITE),--lite) dist/$(NAME).app

app: ## macOS アプリ（dist/OboeGaki.app）をビルド
	rm -rf build dist
	$(UV) run python scripts/make_icon.py
	$(MAKE) _bundle NAME=OboeGaki
	@echo "できました: dist/OboeGaki.app（署名はアドホック。配布には Developer ID が要る）"

run-lite: ## 軽量版の動きをソースから試す（Mermaid はコードのまま出る）
	HITOFUDE_LITE=1 $(UV) run python -m hitofude

app-lite: ## 軽量版（dist/OboeGakiLite.app。Mermaid なし・数式は出る。約 130MB）
	rm -rf build dist
	$(UV) run python scripts/make_icon.py
	$(MAKE) _bundle NAME=OboeGakiLite LITE=1
	@echo "できました: dist/OboeGakiLite.app（軽量版。Mermaid の図はコードのまま出ます）"

# 配る zip に付ける版。**2 か所に書かない**——食い違うと、配ったものが
# どの版か分からなくなる
VERSION := $(shell grep -m1 '^version' pyproject.toml | cut -d'"' -f2)

dist: all ## 配る形（zip）まで作る（版は pyproject.toml から取る）
	@# **`zip -r` を使わない。** Framework の中のシンボリックリンクが壊れ、
	@# 起動しない `.app` ができる。ditto は macOS のメタデータごと保つ
	ditto -c -k --keepParent dist/OboeGaki.app dist/OboeGaki-$(VERSION).zip
	ditto -c -k --keepParent dist/OboeGakiLite.app dist/OboeGakiLite-$(VERSION).zip
	@ls -lh dist/*.zip | awk '{print $$5, $$9}'
	@echo "※ 未署名。受け取った人は初回だけ右クリック →「開く」が要る"

dmg: app ## インストール用 DMG（dist/OboeGaki-版.dmg）を新規ビルドから作る
	@command -v create-dmg >/dev/null 2>&1 || \
		{ echo "create-dmg が無い。brew install create-dmg で入れてください"; exit 1; }
	@# **DMG に入れるものを隔離する。** dist/ を直接渡すと zip などの
	@# 同居物まで巻き込む。ditto なのは zip と同じ理由（シンボリックリンク保全）
	rm -rf build/dmg
	mkdir -p build/dmg
	ditto dist/OboeGaki.app build/dmg/OboeGaki.app
	create-dmg --volname "覚書" --window-size 600 400 \
		--icon "OboeGaki.app" 150 180 --app-drop-link 450 180 \
		dist/OboeGaki-$(VERSION).dmg build/dmg
	@ls -lh dist/OboeGaki-$(VERSION).dmg | awk '{print $$5, $$9}'
	@echo "※ 未署名。受け取った人は初回だけ右クリック →「開く」が要る（§8.2 は Developer ID 待ち）"

all: ## 通常版と軽量版を一度に作る（dist に 2 つ並ぶ）
	rm -rf build dist
	$(UV) run python scripts/make_icon.py
	$(MAKE) _bundle NAME=OboeGaki
	$(MAKE) _bundle NAME=OboeGakiLite LITE=1
	@echo "できました: dist/OboeGaki.app と dist/OboeGakiLite.app"

icon: ## アプリアイコンを再生成
	$(UV) run python scripts/make_icon.py

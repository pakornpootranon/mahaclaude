-- CreateTable
CREATE TABLE "sources" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "name" TEXT NOT NULL,
    "source_type" TEXT NOT NULL,
    "config" JSONB NOT NULL,
    "enabled" BOOLEAN NOT NULL DEFAULT true,
    "poll_override_minutes" INTEGER,
    "language" TEXT NOT NULL DEFAULT 'en',
    "health" TEXT NOT NULL DEFAULT 'ok',
    "consecutive_failures" INTEGER NOT NULL DEFAULT 0,
    "last_success_at" TIMESTAMPTZ,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "sources_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "cycles" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "scheduled_for" TIMESTAMPTZ NOT NULL,
    "kind" TEXT NOT NULL DEFAULT 'scheduled',
    "requested_manual" BOOLEAN NOT NULL DEFAULT false,
    "state" TEXT NOT NULL DEFAULT 'PENDING',
    "stats" JSONB NOT NULL DEFAULT '{}',
    "budget_hit" BOOLEAN NOT NULL DEFAULT false,
    "error" TEXT,
    "started_at" TIMESTAMPTZ,
    "finished_at" TIMESTAMPTZ,

    CONSTRAINT "cycles_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "news_items" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "source_id" UUID NOT NULL,
    "cycle_id" UUID,
    "dedupe_key" TEXT NOT NULL,
    "story_key" TEXT,
    "url" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "summary" TEXT,
    "body_excerpt" TEXT,
    "language" TEXT NOT NULL DEFAULT 'en',
    "published_at" TIMESTAMPTZ,
    "fetched_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "analysis_hints" JSONB,
    "triage_status" TEXT NOT NULL DEFAULT 'pending',

    CONSTRAINT "news_items_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "topics" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "name" TEXT NOT NULL,
    "description" TEXT NOT NULL,
    "keywords" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "sensitivity" DECIMAL(3,2) NOT NULL DEFAULT 0.70,
    "enabled" BOOLEAN NOT NULL DEFAULT true,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "topics_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "mappings" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "topic_id" UUID NOT NULL,
    "market" TEXT NOT NULL,
    "sector" TEXT NOT NULL,
    "tickers" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "polarity" INTEGER NOT NULL,
    "enabled" BOOLEAN NOT NULL DEFAULT true,
    "suggested_by" TEXT NOT NULL DEFAULT 'user',
    "note" TEXT,

    CONSTRAINT "mappings_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "analyses" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "cycle_id" UUID NOT NULL,
    "story_key" TEXT NOT NULL,
    "primary_item_id" UUID NOT NULL,
    "prompt_version" TEXT NOT NULL,
    "model" TEXT NOT NULL,
    "result" JSONB NOT NULL,
    "event_polarity" INTEGER NOT NULL,
    "magnitude" DECIMAL(3,2) NOT NULL,
    "confidence" DECIMAL(3,2) NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "analyses_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "analysis_topics" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "analysis_id" UUID NOT NULL,
    "topic_id" UUID,
    "match_strength" DECIMAL(3,2) NOT NULL,

    CONSTRAINT "analysis_topics_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "recommendations" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "cycle_id" UUID NOT NULL,
    "analysis_id" UUID NOT NULL,
    "topic_id" UUID,
    "dedupe_key" TEXT NOT NULL,
    "action" TEXT NOT NULL,
    "market" TEXT NOT NULL,
    "sector" TEXT NOT NULL,
    "tickers" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "confidence" DECIMAL(3,2) NOT NULL,
    "reasoning" TEXT NOT NULL,
    "rule_trace" JSONB NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "recommendations_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "recommendation_sources" (
    "recommendation_id" UUID NOT NULL,
    "news_item_id" UUID NOT NULL,

    CONSTRAINT "recommendation_sources_pkey" PRIMARY KEY ("recommendation_id","news_item_id")
);

-- CreateTable
CREATE TABLE "outcomes" (
    "recommendation_id" UUID NOT NULL,
    "ticker" TEXT NOT NULL,
    "entry_price" DECIMAL(65,30),
    "ret_1d" DECIMAL(65,30),
    "ret_3d" DECIMAL(65,30),
    "ret_7d" DECIMAL(65,30),
    "hit_1d" BOOLEAN,
    "hit_3d" BOOLEAN,
    "hit_7d" BOOLEAN,
    "status" TEXT NOT NULL DEFAULT 'pending',
    "attempts" INTEGER NOT NULL DEFAULT 0,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "outcomes_pkey" PRIMARY KEY ("recommendation_id")
);

-- CreateTable
CREATE TABLE "digests" (
    "cycle_id" UUID NOT NULL,
    "market_mood" TEXT NOT NULL,
    "synthesis" TEXT NOT NULL,
    "top_themes" JSONB NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "digests_pkey" PRIMARY KEY ("cycle_id")
);

-- CreateTable
CREATE TABLE "settings" (
    "key" TEXT NOT NULL,
    "value" JSONB NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "settings_pkey" PRIMARY KEY ("key")
);

-- CreateTable
CREATE TABLE "llm_calls" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "cycle_id" UUID,
    "purpose" TEXT NOT NULL,
    "model" TEXT NOT NULL,
    "input_tokens" INTEGER NOT NULL,
    "output_tokens" INTEGER NOT NULL,
    "cost_usd" DECIMAL(10,6) NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "llm_calls_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "secrets" (
    "key" TEXT NOT NULL,
    "value" TEXT NOT NULL,
    "last4" TEXT NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "secrets_pkey" PRIMARY KEY ("key")
);

-- CreateTable
CREATE TABLE "pm_markets" (
    "id" TEXT NOT NULL,
    "question" TEXT NOT NULL,
    "slug" TEXT NOT NULL,
    "category" TEXT,
    "end_date" TIMESTAMPTZ,
    "yes_price" DECIMAL(6,4),
    "volume_24h_usd" DECIMAL(65,30),
    "liquidity_usd" DECIMAL(65,30),
    "active" BOOLEAN NOT NULL DEFAULT true,
    "resolved" BOOLEAN NOT NULL DEFAULT false,
    "resolution" TEXT,
    "snapshot_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "pm_markets_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "pm_opportunities" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "cycle_id" UUID NOT NULL,
    "market_id" TEXT NOT NULL,
    "dedupe_key" TEXT NOT NULL,
    "discovery" TEXT NOT NULL,
    "side" TEXT NOT NULL,
    "market_price" DECIMAL(6,4) NOT NULL,
    "est_probability" DECIMAL(6,4) NOT NULL,
    "edge_points" DECIMAL(6,2) NOT NULL,
    "confidence" DECIMAL(3,2) NOT NULL,
    "reasoning" TEXT NOT NULL,
    "rule_trace" JSONB NOT NULL,
    "prompt_version" TEXT NOT NULL,
    "model" TEXT NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "pm_opportunities_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "pm_opportunity_analyses" (
    "pm_opportunity_id" UUID NOT NULL,
    "analysis_id" UUID NOT NULL,

    CONSTRAINT "pm_opportunity_analyses_pkey" PRIMARY KEY ("pm_opportunity_id","analysis_id")
);

-- CreateTable
CREATE TABLE "pm_outcomes" (
    "pm_opportunity_id" UUID NOT NULL,
    "price_1d" DECIMAL(6,4),
    "price_3d" DECIMAL(6,4),
    "price_7d" DECIMAL(6,4),
    "moved_toward_estimate_7d" BOOLEAN,
    "resolved" BOOLEAN NOT NULL DEFAULT false,
    "resolution" TEXT,
    "estimate_correct" BOOLEAN,
    "status" TEXT NOT NULL DEFAULT 'pending',
    "attempts" INTEGER NOT NULL DEFAULT 0,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "pm_outcomes_pkey" PRIMARY KEY ("pm_opportunity_id")
);

-- CreateTable
CREATE TABLE "source_tests" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "source_id" UUID NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'requested',
    "result" JSONB,
    "requested_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "completed_at" TIMESTAMPTZ,

    CONSTRAINT "source_tests_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "cycles_scheduled_for_idx" ON "cycles"("scheduled_for" DESC);

-- CreateIndex
CREATE UNIQUE INDEX "news_items_dedupe_key_key" ON "news_items"("dedupe_key");

-- CreateIndex
CREATE INDEX "news_items_story_key_idx" ON "news_items"("story_key");

-- CreateIndex
CREATE INDEX "news_items_published_at_idx" ON "news_items"("published_at" DESC);

-- CreateIndex
CREATE UNIQUE INDEX "topics_name_key" ON "topics"("name");

-- CreateIndex
CREATE UNIQUE INDEX "mappings_topic_id_market_sector_key" ON "mappings"("topic_id", "market", "sector");

-- CreateIndex
CREATE UNIQUE INDEX "analyses_story_key_prompt_version_key" ON "analyses"("story_key", "prompt_version");

-- CreateIndex
CREATE UNIQUE INDEX "analysis_topics_analysis_id_topic_id_key" ON "analysis_topics"("analysis_id", "topic_id");

-- CreateIndex
CREATE UNIQUE INDEX "recommendations_dedupe_key_key" ON "recommendations"("dedupe_key");

-- CreateIndex
CREATE INDEX "recommendations_created_at_idx" ON "recommendations"("created_at" DESC);

-- CreateIndex
CREATE INDEX "llm_calls_created_at_idx" ON "llm_calls"("created_at");

-- CreateIndex
CREATE INDEX "pm_markets_active_volume_24h_usd_idx" ON "pm_markets"("active", "volume_24h_usd" DESC);

-- CreateIndex
CREATE UNIQUE INDEX "pm_opportunities_dedupe_key_key" ON "pm_opportunities"("dedupe_key");

-- CreateIndex
CREATE INDEX "pm_opportunities_created_at_idx" ON "pm_opportunities"("created_at" DESC);

-- AddForeignKey
ALTER TABLE "news_items" ADD CONSTRAINT "news_items_source_id_fkey" FOREIGN KEY ("source_id") REFERENCES "sources"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "news_items" ADD CONSTRAINT "news_items_cycle_id_fkey" FOREIGN KEY ("cycle_id") REFERENCES "cycles"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "mappings" ADD CONSTRAINT "mappings_topic_id_fkey" FOREIGN KEY ("topic_id") REFERENCES "topics"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "analyses" ADD CONSTRAINT "analyses_cycle_id_fkey" FOREIGN KEY ("cycle_id") REFERENCES "cycles"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "analyses" ADD CONSTRAINT "analyses_primary_item_id_fkey" FOREIGN KEY ("primary_item_id") REFERENCES "news_items"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "analysis_topics" ADD CONSTRAINT "analysis_topics_analysis_id_fkey" FOREIGN KEY ("analysis_id") REFERENCES "analyses"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "analysis_topics" ADD CONSTRAINT "analysis_topics_topic_id_fkey" FOREIGN KEY ("topic_id") REFERENCES "topics"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "recommendations" ADD CONSTRAINT "recommendations_cycle_id_fkey" FOREIGN KEY ("cycle_id") REFERENCES "cycles"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "recommendations" ADD CONSTRAINT "recommendations_analysis_id_fkey" FOREIGN KEY ("analysis_id") REFERENCES "analyses"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "recommendations" ADD CONSTRAINT "recommendations_topic_id_fkey" FOREIGN KEY ("topic_id") REFERENCES "topics"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "recommendation_sources" ADD CONSTRAINT "recommendation_sources_recommendation_id_fkey" FOREIGN KEY ("recommendation_id") REFERENCES "recommendations"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "recommendation_sources" ADD CONSTRAINT "recommendation_sources_news_item_id_fkey" FOREIGN KEY ("news_item_id") REFERENCES "news_items"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "outcomes" ADD CONSTRAINT "outcomes_recommendation_id_fkey" FOREIGN KEY ("recommendation_id") REFERENCES "recommendations"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "digests" ADD CONSTRAINT "digests_cycle_id_fkey" FOREIGN KEY ("cycle_id") REFERENCES "cycles"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "llm_calls" ADD CONSTRAINT "llm_calls_cycle_id_fkey" FOREIGN KEY ("cycle_id") REFERENCES "cycles"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "pm_opportunities" ADD CONSTRAINT "pm_opportunities_cycle_id_fkey" FOREIGN KEY ("cycle_id") REFERENCES "cycles"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "pm_opportunities" ADD CONSTRAINT "pm_opportunities_market_id_fkey" FOREIGN KEY ("market_id") REFERENCES "pm_markets"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "pm_opportunity_analyses" ADD CONSTRAINT "pm_opportunity_analyses_pm_opportunity_id_fkey" FOREIGN KEY ("pm_opportunity_id") REFERENCES "pm_opportunities"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "pm_opportunity_analyses" ADD CONSTRAINT "pm_opportunity_analyses_analysis_id_fkey" FOREIGN KEY ("analysis_id") REFERENCES "analyses"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "pm_outcomes" ADD CONSTRAINT "pm_outcomes_pm_opportunity_id_fkey" FOREIGN KEY ("pm_opportunity_id") REFERENCES "pm_opportunities"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "source_tests" ADD CONSTRAINT "source_tests_source_id_fkey" FOREIGN KEY ("source_id") REFERENCES "sources"("id") ON DELETE CASCADE ON UPDATE CASCADE;

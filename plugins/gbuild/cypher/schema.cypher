// gbuild store schema. Run once, when plan creates the store:
//   cypherlite .gbuild/<slug>/db --snapshot-format json < cypher/schema.cypher
// Everything the engine can enforce at write time lives here; the rest of the
// contract is checked by validate.cypher.
CREATE CONSTRAINT feature_name FOR (n:Feature) REQUIRE n.feature IS :: STRING;
CREATE CONSTRAINT feature_name_exists FOR (n:Feature) REQUIRE n.feature IS NOT NULL;
CREATE CONSTRAINT feature_destination FOR (n:Feature) REQUIRE n.destination IS :: STRING;
CREATE CONSTRAINT feature_destination_exists FOR (n:Feature) REQUIRE n.destination IS NOT NULL;
CREATE CONSTRAINT feature_context FOR (n:Feature) REQUIRE n.context IS :: STRING;
CREATE CONSTRAINT feature_context_exists FOR (n:Feature) REQUIRE n.context IS NOT NULL;
CREATE CONSTRAINT feature_out_of_scope FOR (n:Feature) REQUIRE n.out_of_scope IS :: LIST<STRING NOT NULL>;
CREATE CONSTRAINT feature_out_of_scope_exists FOR (n:Feature) REQUIRE n.out_of_scope IS NOT NULL;
CREATE CONSTRAINT acceptance_id FOR (n:Acceptance) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT acceptance_id_exists FOR (n:Acceptance) REQUIRE n.id IS NOT NULL;
CREATE CONSTRAINT acceptance_text FOR (n:Acceptance) REQUIRE n.text IS :: STRING;
CREATE CONSTRAINT acceptance_text_exists FOR (n:Acceptance) REQUIRE n.text IS NOT NULL;
CREATE CONSTRAINT node_slug FOR (n:GbuildNode) REQUIRE n.slug IS UNIQUE;
CREATE CONSTRAINT node_slug_exists FOR (n:GbuildNode) REQUIRE n.slug IS NOT NULL;
CREATE CONSTRAINT node_title FOR (n:GbuildNode) REQUIRE n.title IS :: STRING;
CREATE CONSTRAINT node_title_exists FOR (n:GbuildNode) REQUIRE n.title IS NOT NULL;
CREATE CONSTRAINT node_type FOR (n:GbuildNode) REQUIRE n.type IS :: STRING;
CREATE CONSTRAINT node_type_exists FOR (n:GbuildNode) REQUIRE n.type IS NOT NULL;
CREATE CONSTRAINT node_acceptance FOR (n:GbuildNode) REQUIRE n.acceptance IS :: LIST<STRING NOT NULL>;
CREATE CONSTRAINT node_acceptance_exists FOR (n:GbuildNode) REQUIRE n.acceptance IS NOT NULL;
CREATE CONSTRAINT node_failure_policy FOR (n:GbuildNode) REQUIRE n.failure_policy IS :: STRING;
CREATE CONSTRAINT node_failure_policy_exists FOR (n:GbuildNode) REQUIRE n.failure_policy IS NOT NULL;
CREATE CONSTRAINT node_model_tier FOR (n:GbuildNode) REQUIRE n.model_tier IS :: STRING;
CREATE CONSTRAINT node_model_tier_exists FOR (n:GbuildNode) REQUIRE n.model_tier IS NOT NULL;
CREATE CONSTRAINT node_status FOR (n:GbuildNode) REQUIRE n.status IS :: STRING;
CREATE CONSTRAINT node_status_exists FOR (n:GbuildNode) REQUIRE n.status IS NOT NULL;
CREATE CONSTRAINT node_verify FOR (n:GbuildNode) REQUIRE n.verify IS :: STRING;
CREATE CONSTRAINT node_started_at FOR (n:GbuildNode) REQUIRE n.started_at IS :: STRING;
CREATE CONSTRAINT node_completed_at FOR (n:GbuildNode) REQUIRE n.completed_at IS :: STRING;
CREATE CONSTRAINT field_name FOR (n:Field) REQUIRE n.name IS :: STRING;
CREATE CONSTRAINT field_name_exists FOR (n:Field) REQUIRE n.name IS NOT NULL;
CREATE CONSTRAINT field_shape FOR (n:Field) REQUIRE n.shape IS :: STRING;
CREATE CONSTRAINT field_shape_exists FOR (n:Field) REQUIRE n.shape IS NOT NULL;
CREATE CONSTRAINT review_attempt FOR (n:Review) REQUIRE n.attempt IS :: INTEGER;
CREATE CONSTRAINT review_attempt_exists FOR (n:Review) REQUIRE n.attempt IS NOT NULL;
CREATE CONSTRAINT review_verdict FOR (n:Review) REQUIRE n.verdict IS :: STRING;
CREATE CONSTRAINT review_verdict_exists FOR (n:Review) REQUIRE n.verdict IS NOT NULL;
CREATE CONSTRAINT review_at FOR (n:Review) REQUIRE n.at IS :: STRING;
CREATE CONSTRAINT review_at_exists FOR (n:Review) REQUIRE n.at IS NOT NULL;
CREATE CONSTRAINT review_failed_criteria FOR (n:Review) REQUIRE n.failed_criteria IS :: LIST<STRING NOT NULL>;
.checkpoint

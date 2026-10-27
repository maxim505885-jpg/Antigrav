import assert from "node:assert/strict";
import test from "node:test";
import {
  annotationReviewerFor,
  rememberAnnotationReviewer,
  resetAnnotationReviewersForTests,
} from "./annotationReviewer.ts";

test("reuses the reviewer name for another candidate in the same cloud session", () => {
  resetAnnotationReviewersForTests();
  rememberAnnotationReviewer("cloud-a", "  Maxim  ");

  assert.equal(annotationReviewerFor("cloud-a"), "Maxim");
  assert.equal(annotationReviewerFor("cloud-b"), "");
});

test("a saved annotation keeps its original reviewer name", () => {
  resetAnnotationReviewersForTests();
  rememberAnnotationReviewer("cloud-a", "Current reviewer");

  assert.equal(annotationReviewerFor("cloud-a", "Earlier reviewer"), "Earlier reviewer");
});

test("clearing the reviewer removes the session default", () => {
  resetAnnotationReviewersForTests();
  rememberAnnotationReviewer("cloud-a", "Maxim");
  rememberAnnotationReviewer("cloud-a", "  ");

  assert.equal(annotationReviewerFor("cloud-a"), "");
});

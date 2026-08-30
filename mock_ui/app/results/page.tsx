import { Suspense } from "react";
import { ResultsExperience } from "@/components/results/ResultsExperience";

export default function ResultsPage() {
  return (
    <Suspense>
      <ResultsExperience />
    </Suspense>
  );
}

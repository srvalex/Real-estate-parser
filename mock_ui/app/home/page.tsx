import { Suspense } from "react";
import { SearchExperience } from "@/components/search/SearchExperience";

export default function HomePage() {
  return (
    <Suspense>
      <SearchExperience />
    </Suspense>
  );
}

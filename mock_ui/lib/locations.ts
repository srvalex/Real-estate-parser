import districtsJson from "./data/districts.json";

// Country-wide location tree. Most cities are flat (a city has neighborhoods
// directly); a few — București foremost — are split into districts (sectors)
// that each hold their own neighborhoods. Bucharest's TODO: replace with the
// official nation-wide dataset once available; other cities (Timișoara,
// Oradea, ...) will slot in here, most of them via `zones` rather than
// `districts` since they have no sector-level grouping.
export type LocationDistrict = {
  name: string;
  zones: string[];
};

export type LocationCity =
  | { city: string; districts: LocationDistrict[]; zones?: undefined }
  | { city: string; districts?: undefined; zones: string[] };

export function getLocations(): LocationCity[] {
  const districts = districtsJson as Record<string, string[]>;
  return [
    {
      city: "București",
      districts: Object.entries(districts).map(([name, zones]) => ({ name, zones })),
    },
  ];
}

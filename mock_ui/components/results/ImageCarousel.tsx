"use client";

import { useRef, useState } from "react";
import Image from "next/image";
import clsx from "clsx";
import type { ListingImage, PropertyType } from "@/lib/types";
import { MissingPhotoFallback } from "./MissingPhotoFallback";

export function ImageCarousel({ images, alt, propertyType }: { images: ListingImage[]; alt: string; propertyType: PropertyType }) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [index, setIndex] = useState(0);

  if (images.length === 0) {
    return (
      <div className="h-48 w-full">
        <MissingPhotoFallback type={propertyType} />
      </div>
    );
  }

  function handleScroll() {
    const el = trackRef.current;
    if (!el) return;
    const i = Math.round(el.scrollLeft / el.clientWidth);
    setIndex(i);
  }

  return (
    <div className="relative h-48 w-full overflow-hidden bg-paper-dim">
      <div
        ref={trackRef}
        onScroll={handleScroll}
        className="flex h-full snap-x snap-mandatory overflow-x-auto scroll-smooth"
      >
        {images.map((img, i) => (
          <div key={i} className="relative h-full w-full flex-shrink-0 snap-center">
            <Image
              src={img.medium ?? img.small ?? img.thumbnail ?? ""}
              alt={i === 0 ? alt : `${alt}, foto ${i + 1}`}
              fill
              sizes="(max-width: 640px) 100vw, 400px"
              className="object-cover"
              loading="lazy"
            />
          </div>
        ))}
      </div>

      {images.length > 1 && (
        <div className="pointer-events-none absolute bottom-2 left-1/2 flex -translate-x-1/2 gap-1">
          {images.map((_, i) => (
            <span
              key={i}
              className={clsx(
                "h-1.5 w-1.5 rounded-full transition-colors",
                i === index ? "bg-paper" : "bg-paper/50"
              )}
            />
          ))}
        </div>
      )}
    </div>
  );
}

"""
rrf.py
──────
Reciprocal Rank Fusion — pure ranking math, no dependencies. Kept out of
streamlit_interface/pipeline/utils.py so it can be reused (e.g. by demo/
scripts) without pulling in Streamlit/pandas.
"""


def rrf_fuse(
    text_scores: dict,
    image_scores: dict,
    urls,
    k: int = 60,
    w_text: float = 0.3,
    w_image: float = 0.7,
) -> dict:
    """Reciprocal Rank Fusion of two independent similarity-score dicts.

    Raw cosine similarities from ST (384-dim) and CLIP (512-dim) are not
    comparable — different models, different score distributions. RRF fuses
    them purely by ordinal rank, making the weights scale-independent:

        rrf(url) = w_text / (k + text_rank(url)) + w_image / (k + image_rank(url))

    k=60 is the standard dampening constant. A URL absent from a ranked list
    contributes 0 for that term (infinite rank). Returns raw (non-normalised)
    RRF scores for every url in `urls` that scored > 0.
    """
    def _rank_map(scores: dict) -> dict:
        return {
            url: rank
            for rank, (url, _) in enumerate(
                sorted(scores.items(), key=lambda x: x[1], reverse=True), start=1
            )
        }

    text_ranks  = _rank_map(text_scores)  if text_scores  else {}
    image_ranks = _rank_map(image_scores) if image_scores else {}

    final_scores: dict = {}
    for url in urls:
        t_rank = text_ranks.get(url)
        i_rank = image_ranks.get(url)
        score  = 0.0
        if t_rank is not None:
            score += w_text  / (k + t_rank)
        if i_rank is not None:
            score += w_image / (k + i_rank)
        if score > 0:
            final_scores[url] = score
    return final_scores

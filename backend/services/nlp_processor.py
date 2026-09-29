import spacy

try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    print("Downloading Spacy model....")
    nlp = spacy.load("en_core_web_sm")


def chunk_text(raw_text: str, max_words_per_chunk: int = 400, overlap_words: int = 50, pipeline_stats: dict | None = None):
    """
    chunks text by sentences using a sliding window overlap.
    Implements Recursive Character Chunking logic but guarantees sentence integrity.
    """
    if not raw_text or not raw_text.strip():
        return []
    
    #clean the text of any corrupted pdf surrogate charaters
    clean_text = raw_text.encode("utf-8", 'ignore').decode('utf-8')
    
    # Process the text through the spaCy NLP pipeline

    doc = nlp(clean_text)
    sentences = [sent.text.strip() for sent in doc.sents if sent.text.strip()]

    chunks = []
    current_chunk = []
    current_word_count = 0

    sentence_word_counts = [len(sent.split()) for sent in sentences]

    i = 0
    while i < len(sentences):
        sent_text = sentences[i]
        sent_word_count = sentence_word_counts[i]
        
        # Scenario A: Sentence fits into current chunk
        if current_word_count + sent_word_count <= max_words_per_chunk:
            current_chunk.append(sent_text)
            current_word_count += sent_word_count
            i += 1
        # Scenario B: Chunk is full, finalize it and build overlap
        else:
            if current_chunk:
                chunks.append(" ".join(current_chunk))
            
            # Step backward to collect sentences matching the desired overlap constraint
            overlap_sentences = []
            overlap_word_accumulator = 0
            
            # Walk backward from the current sentence index
            for j in range(i - 1, -1, -1):
                word_len = sentence_word_counts[j]
                if overlap_word_accumulator + word_len <= overlap_words:
                    overlap_sentences.insert(0, sentences[j])
                    overlap_word_accumulator += word_len
                else:
                    break
            
            # Initialize next window using the accumulated overlapping sentences
            current_chunk = overlap_sentences
            current_word_count = overlap_word_accumulator
            
            # Append current sentence to the newly built context window
            current_chunk.append(sent_text)
            current_word_count += sent_word_count
            i += 1

    # Flush remaining sentences to the final chunk
    if current_chunk:
        chunks.append(" ".join(current_chunk))

    print(f"\n--- NLP PIPELINE ---")
    print(f"sanitised raw text.")
    print(f"Tokenized {len(sentences)} sentences.")
    print(f"Generated {len(chunks)} contextual chunks with 50-word sliding overlap.\n")

    if pipeline_stats is not None:
        pipeline_stats.update({
            "sanitised": True,
            "sentence_count": len(sentences),
            "chunk_count": len(chunks),
            "overlap_words": overlap_words,
        })

    return chunks
        
    
    



import editdistance
import re

from collections import defaultdict
from fuzzywuzzy import fuzz

### Helper functions

def get_prefixes(entity, min_length=3, max_length=5):
    # computer science => ['comp sci', ...]
    words = entity.split()
    candidates = ['']
    for word in words:
        new_candidates = []
        for c in candidates:
            if len(word) < max_length:  # Keep word
                new_candidates.append(c + ' ' + word)
            else:
                for i in range(min_length, max_length):
                    new_candidates.append(c + '' + word[:i])
        candidates = new_candidates

    stripped = [c.strip() for c in candidates if c != entity]
    return stripped

def get_acronyms(entity):
    """
    Computes acronyms of entity, assuming entity has more than one token
    :param entity:
    :return:
    """
    words = entity.split()
    first_letters = ''.join([w[0] for w in words])
    acronyms = [first_letters]

    # Add acronyms using smaller number of first letters in phrase ('ucb' -> 'uc')
    for split in range(2, len(first_letters)):
        acronyms.append(first_letters[:split])

    return acronyms


alphabet = "abcdefghijklmnopqrstuvwxyz "
def get_edits(entity):
    if len(entity) < 3:
        return []
    edits = []
    for i in range(len(entity) + 1):
        prefix = entity[:i]
        # Insert
        suffix = entity[i:]
        for c in alphabet:
            new_word = prefix + c + suffix
            edits.append(new_word)

        if i == len(entity):
            continue

        # Delete
        suffix = entity[i+1:]
        new_word = prefix + suffix
        edits.append(new_word)

        # Substitute
        suffix = entity[i+1:]
        for c in alphabet:
            if c != entity[i]:
                new_word = prefix + c + suffix
                edits.append(new_word)

        # Transposition - swapping two letters
        for j in range(i+1, len(entity)):
            mid = entity[i+1:j]
            suffix = entity[j+1:]
            new_word = prefix + entity[j] + mid + entity[i] + suffix
            new_word = new_word.strip()
            if new_word != entity:
                edits.append(new_word)
    return edits


def get_morphological_variants(entity):
    """
    Computes stem of entity and creates morphological variants
    :param entity:
    :return:
    """
    results = []
    for suffix in ['ing']:
        if entity.endswith(suffix):
            base = entity[:-len(suffix)]
            results.append(base)
            # TODO: Can we get away with not hard-coding these variants?
            results.append(base + 'e')
            results.append(base + 's')
            results.append(base + 'er')
            results.append(base + 'ers')
    return results

############################################################

class BaseLexicon(object):
    """
    Base lexicon class defining general purpose functions for any lexicon
    """
    def __init__(self, schema, learned_lex):
        self.schema = schema
        # if True, lexicon uses learned system
        self.learned_lex = learned_lex
        self.entities = {}  # Mapping from (canonical) entity to type (assume type is unique)
        self.word_counts = defaultdict(int)  # Counts of words that show up in entities
        self.lexicon = defaultdict(list)  # Mapping from string -> list of (entity, type)
        self.load_entities()
        self.compute_synonyms()
        print 'Created lexicon: %d phrases mapping to %d entities, %f entities per phrase' % (len(self.lexicon), len(self.entities), sum([len(x) for x in self.lexicon.values()])/float(len(self.lexicon)))


    def load_entities(self):
        for type_, values in self.schema.values.iteritems():
            for value in values:
                self._add_entity(type_, value.lower())

    def _add_entity(self, type, entity):
        # Keep track of number of times words in this entity shows up
        if entity not in self.entities:
            for word in entity.split(' '):
                self.word_counts[word] += 1
        self.entities[entity] = type

    def lookup(self, phrase):
        return self.lexicon.get(phrase, [])



class Lexicon(BaseLexicon):
    """
    Lexicon that only computes per token entity transforms rather than per phrase transforms (except for prefixes/acronyms)
    """
    def __init__(self, schema, learned_lex=False):
        super(Lexicon, self).__init__(schema, learned_lex)
        # TODO: Remove hard-coding (use list of common words/phrases/stop words)
        self.common_phrases = set(["went", "to", "and", "of", "my", "the", "names", "any",
                                   "friends", "at", "for", "in", "many", "partner", "all", "we",
                                   "start", "go", "school"])


    def compute_synonyms(self):
        """
        Computes all variants (synonyms) for each token of every canonical entity
        :return:
        """
        # Keep track of tokens we have seen to handle repeats
        for entity, type in self.entities.items():
            phrases = []
            mod_entity = entity
            for s in [' of ', ' - ', '-']:
                mod_entity = mod_entity.replace(s, ' ')

            # Add all tokens in entity -- we only compute token-level edits (except for acronyms/prefixes...)
            entity_tokens = mod_entity.split(' ')
            phrases.extend([t for t in entity_tokens])

            synonyms = []
            if entity == 'facebook':
                synonyms.append('fb')

            # General
            for phrase in phrases:
                synonyms.append(phrase)
                if type != 'person':
                    synonyms.extend(get_edits(phrase))
                    synonyms.extend(get_morphological_variants(phrase))
                    synonyms.extend(get_prefixes(phrase, min_length=1))

            # Multi-token level variants: UPenn, uc berkeley
            if len(mod_entity.split(" ")) > 1:
                phrase_level_prefixes = get_prefixes(mod_entity, min_length=1, max_length=5)
                phrase_level_acronyms = get_acronyms(mod_entity)
                synonyms.extend(phrase_level_acronyms)
                synonyms.extend(phrase_level_prefixes)


            # Add to lexicon
            for synonym in set(synonyms):
                self.lexicon[synonym].append((entity, type))


    def score_and_match(self, span, candidates):
        """
        Score the given span with the list of candidate entities and returns best match
        :param span:
        :param candidates:
        :return:
        """
        entity_scores = []
        for c in candidates:
            # Clean up punctuation
            c_s = re.sub("-", " ", c[0])
            span_tokens = span.split()
            entity_tokens = c_s.split()
            # Ideally would do this for major/company as well but too many common words picked up
            if span in entity_tokens and (c[1] == "school"):
                score = 1
            # Prioritize multi phrase spans contained in entity
            elif len(span_tokens) > 1 and span in c_s:
                score = 1
            else:
                score = editdistance.eval(span, c[0])
            entity_scores.append(c + (score,))

        # Sort entity scores
        entity_scores = sorted(entity_scores, key=lambda x: x[2])

        # If exact match or substring match with an entity
        if entity_scores[0][2] <= 1:
            if span not in self.common_phrases:
                best_match = entity_scores[0][:2]
            else:
                best_match = (span, None)
        else:
            best_match = (span, None)

        return best_match


    def link_entity(self, raw_tokens, return_entities=False):
        """
        Add detected entities to each token
        Example: ['i', 'work', 'at', 'apple'] => ['i', 'work', 'at', ('apple', 'company')]
        Note: Linking works differently here because we are considering intersection of lists across
        token spans so that "univ of penn" will lookup in our lexicon table for "univ" and "penn"
        (disregarding stop words and special tokens) and find their intersection
        """
        i = 0
        found_entities = []
        entities = []
        stop_words = set(['of'])
        while i < len(raw_tokens):
            candidate_entities = None
            single_char = False
            # Find longest phrase (if any) that matches an entity
            for l in range(6, 0, -1):
                phrase = ' '.join(raw_tokens[i:i+l])
                raw = raw_tokens[i:i+l]

                for idx, token in enumerate(raw):
                    results = self.lookup(token)
                    if idx == 0: candidate_entities = results
                    if token not in stop_words:
                        candidate_entities = list(set(candidate_entities).intersection(set(results)))

                # Single character token so disregard candidate entities
                if l == 1 and len(phrase) == 1:
                    single_char = True
                    break

                # Found some match
                if len(candidate_entities) > 0:
                    entity = None
                    best_match = self.score_and_match(phrase, candidate_entities)
                    # If best_match is entity from KB add to list
                    if best_match[1] is not None:
                        entities.append((phrase, best_match))
                        found_entities.append((phrase, best_match[0]))
                        i += l
                        break
                    else:
                        candidate_entities = None
                        continue

            if not candidate_entities or single_char:
                entities.append(raw_tokens[i])
                i += 1

        # For computing per dialogue entities found
        if return_entities:
            return entities, found_entities

        return entities


    def test(self):
        sentence3 = "I went to University of Pensylvania and most my friends are from there".split(" ")
        sentence3 = "Dylan at Fenway"
        sentence3 = [t.lower() for t in sentence3.split()]

        sentence2 = ["connecticut"]
        print self.link_entity(sentence3, True)
        print self.link_entity(sentence2, True)


if __name__ == "__main__":
    from schema import Schema
    import argparse
    import time

    parser = argparse.ArgumentParser("arguments for basic testing lexicon")
    parser.add_argument("--schema", type=str, help="path to schema to use")
    args = parser.parse_args()

    path = args.schema
    start_build = time.time()
    schema = Schema(path)
    lex = Lexicon(schema, learned_lex=True)
    print "Building complete: ", time.time() - start_build
    start_test = time.time()
    lex.test()
    print "Testing Complete: ", time.time() - start_test




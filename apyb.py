import sys

import refract
from ply import lex, yacc
from refract.json import JSONSerialiser


#
# Reserved keywords
#
keywords = ('OBJECT', 'STRING', 'BOOLEAN', 'NUMBER', 'FIXED', 'FIXED_TYPE',
            'ENUM', 'ARRAY', )

tokens = keywords + ('TYPE', 'LPAR', 'RPAR', 'LBRAC', 'RBRAC', 'HEADER', 'WS',
                     'NEWLINE', 'COMMA', 'DASH', 'PLUS', 'SEMICOLON', 'TEXT',
                     'MEMBERS', 'PROPERTIES', 'NUM', 'DATASTRUCTURES',
                     'INDENT', 'DEDENT', 'ENDMARKER')


def t_HEADER(t):
    r'\#+'
    return t


# Whitespace
def t_WS(t):
    r'[ \t]+'
    if t.lexer.at_line_start and t.lexer.paren_count == 0:
        return t


# Don't generate newline tokens when inside of parenthesis, eg
def t_newline(t):
    r'\n+'
    t.lexer.lineno += len(t.value)
    t.type = "NEWLINE"
    if t.lexer.paren_count == 0:
        return t


def t_NUM(t):
    r'(\d+(\.\d*)?|\.\d+)([eE][-+]? \d+)?'
    return t


def t_FIXED_TYPE(t):
    r'fixed-type'
    return t


def t_FIXED(t):
    r'fixed'
    return t


def t_MEMBERS(t):
    r'[M|m]ember[s]'
    return t


def t_PROPERTIES(t):
    r'[P|p]roperties'
    return t


def t_STRING(t):
    r'string'
    return t


def t_NUMBER(t):
    r'number'
    return t


def t_BOOLEAN(t):
    r'boolean'
    return t


def t_OBJECT(t):
    r'object'
    return t


def t_ARRAY(t):
    r'array'
    return t


def t_ENUM(t):
    r'enum'
    return t


def t_COMMA(t):
    r','
    return t


def t_DATASTRUCTURES(t):
    r'[D|d]ata\s*[S|s]tructure[s]'
    return t


def t_TEXT(t):
    r'([^#\-\+\t\r\f\v\n()\[\],]+)'  # I think this is right ...
    return t


def t_LPAR(t):
    r'\('
    t.lexer.paren_count += 1
    return t


def t_RPAR(t):
    r'\)'
    # check for underflow?  should be the job of the parser
    t.lexer.paren_count -= 1
    return t


def t_LBRAC(t):
    r'\['
    t.lexer.paren_count += 1
    return t


def t_RBRAC(t):
    r'\]'
    # check for underflow?  should be the job of the parser
    t.lexer.paren_count -= 1
    return t


def t_DASH(t):
    r'\s*\-'
    return t


def t_PLUS(t):
    r'\s*\+'
    return t


def t_error(t):
    raise SyntaxError("Unknown symbol %r : %r" % (t.value, t))
    print("Skipping", repr(t.value[0]))
    t.lexer.skip(1)


# I implemented INDENT / DEDENT generation as a post-processing filter
# The original lex token stream contains WS and NEWLINE characters.
# WS will only occur before any other tokens on a line.
# only care about whitespace at the start of a line
def track_tokens_filter(lexer, tokens):
    lexer.at_line_start = at_line_start = True
    for token in tokens:
        token.at_line_start = at_line_start

        if token.type == "NEWLINE":
            at_line_start = True

        elif token.type == "WS":
            assert token.at_line_start is True
            at_line_start = True

        else:
            # A real token; only indent after COLON NEWLINE
            at_line_start = False

        yield token
        lexer.at_line_start = at_line_start


def _new_token(type, lineno, lexpos=0):
    tok = lex.LexToken()
    tok.type = type
    tok.value = None
    tok.lineno = lineno
    tok.lexpos = lexpos
    return tok


# Synthesize a INDENT and DEDENT
def DEDENT(lineno, lexpos=0):
    return _new_token("DEDENT", lineno, lexpos)


def INDENT(lineno, lexpos=0):
    return _new_token("INDENT", lineno, lexpos)


# Track the indentation level and emit the right INDENT / DEDENT events.
def indentation_filter(tokens):
    # A stack of indentation levels; will never pop item 0
    levels = [0]
    token = None
    depth = 0
    for token in tokens:
        # if 1:
        # print "Process", token,
        # if token.at_line_start:
        # print "at_line_start",
        # if token.must_indent:
        # print "must_indent",
        # print

        # WS only occurs at the start of the line
        # There may be WS followed by NEWLINE so
        # only track the depth here.  Don't indent/dedent
        # until there's something real.
        if token.type == "WS":
            assert depth == 0
            depth = len(token.value)
            # WS tokens are never passed to the parser
            continue

        if token.type == "NEWLINE":
            depth = 0
            yield token
            continue

        # then it must be a real token (not WS, not NEWLINE)
        # which can affect the indentation level
        if token.at_line_start:
            # Must be on the same level or one of the previous levels
            if depth == levels[-1]:
                # At the same level
                pass
            elif depth > levels[-1]:
                levels.append(depth)
                yield INDENT(token.lineno, token.lexpos - depth)
            else:
                # Back up; but only if it matches a previous level
                try:
                    i = levels.index(depth)
                except ValueError:
                    raise IndentationError("inconsistent indentation")
                for x in range(i + 1, len(levels)):
                    yield DEDENT(token.lineno, token.lexpos - depth)
                    levels.pop()

        yield token

    # Finished processing #

    # Must dedent any remaining levels
    if len(levels) > 1:
        assert token is not None
        for _ in range(1, len(levels)):
            yield DEDENT(token.lineno, token.lexpos)


# The top-level filter adds an ENDMARKER, if requested.
# Python's grammar uses it.
def filter(lexer, add_endmarker=True):
    token = None
    tokens = iter(lexer.token, None)
    tokens = track_tokens_filter(lexer, tokens)
    for token in indentation_filter(tokens):
        yield token

    if add_endmarker:
        lineno = 1
        lexpos = 0
        if token is not None:
            lineno = token.lineno
            lexpos = token.lexpos
        yield _new_token("ENDMARKER", lineno, lexpos)


# Combine Ply and my filters into a new lexer


class IndentLexer(object):
    def __init__(self, debug=0, optimize=0, lextab='lextab', reflags=0):
        self.lexer = lex.lex(
            debug=debug, optimize=optimize, lextab=lextab, reflags=reflags)
        self.token_stream = None

    def input(self, s, add_endmarker=True):
        self.lexer.paren_count = 0
        self.lexer.input(s)
        self.token_stream = filter(self.lexer, add_endmarker)

    def token(self):
        try:
            return next(self.token_stream)
        except StopIteration as e:
            return None


# Parser (tokens -> AST)
def p_error(p):
    print(p)


def p_result(p):
    ''' result : header_objects ENDMARKER
               | data_structs header_objects ENDMARKER'''
    if len(p) > 3:
        p[0] = refract.Array(content=p[2])
    else:
        p[0] = refract.Array(content=p[1])


def p_data_structs(p):
    ''' data_structs : HEADER DATASTRUCTURES NEWLINE'''


def p_header_objects(p):
    '''header_objects : header_objects header_object
                      | header_object '''
    if len(p) > 2:
        p[0] = p[1]
        p[0].append(p[2])
    else:
        p[0] = [p[1]]


def p_header_object(p):
    '''header_object : HEADER TEXT type_def NEWLINE object_items
                     | HEADER TEXT NEWLINE object_items
                     | HEADER TEXT NEWLINE description NEWLINE object_items
                     | HEADER TEXT type_def NEWLINE description NEWLINE object_items
                     | HEADER TEXT type_def NEWLINE '''

    meta = refract.Metadata(id=refract.String(content=p[2]))
    attributes = refract.Attributes()
    try:
        attributes['typeAttributes'] = p[3].__dict__['apyb']
    except (AttributeError, KeyError):
        pass

    if len(p) == 8:
        meta.description = refract.String(content=p[5])
        p[0] = refract.Object(content=p[7],
                              meta=meta,
                              attributes=attributes)
    elif len(p) == 7:
        meta.description = refract.String(content=p[4])
        p[0] = refract.Object(content=p[6],
                              meta=meta,
                              attributes=attributes)
    elif len(p) > 5:
        p[0] = refract.Object(content=p[5], meta=meta, attributes=attributes)
    else:
        if not isinstance(p[3], str):
            p[3].meta = meta
            p[3].attributes = attributes
        else:
            p[0] = refract.Object(
                content=p[4], meta=meta, attributes=attributes)


def p_description(p):
    ''' description : TEXT NEWLINE TEXT
                    | description TEXT NEWLINE TEXT'''

    if p[0] is None:
        p[0] = ""
    for i in p[1:]:
        p[0] += i


def p_type_def(p):
    '''type_def : LPAR OBJECT  type_spec RPAR
                | LPAR NUMBER  type_spec RPAR
                | LPAR BOOLEAN type_spec RPAR
                | LPAR STRING  type_spec RPAR
                | LPAR ENUM    type_spec RPAR
                | LPAR TEXT    type_spec RPAR
                | LPAR array_def type_spec RPAR'''

    if isinstance(p[2], refract.Array):
        p[0] = p[2]
    elif p[2] == 'number':
        p[0] = refract.Number()
    elif p[2] == 'object':
        p[0] = refract.Object()
    elif p[2] == 'boolean':
        p[0] = refract.Boolean()
    elif p[2] == 'string':
        p[0] = refract.String()
    else:
        p[0] = refract.Element(element=p[2])

    if p[3] is not None:
        p[0].__dict__['apyb'] = [p[3]]


def p_array_def(p):
    ''' array_def : ARRAY
                  | ARRAY LBRAC TEXT RBRAC'''
    if len(p) > 2:
        p[0] = refract.Array(content=[refract.Element(element=p[3])])
    else:
        p[0] = refract.Array()


def p_type_spec(p):
    ''' type_spec : COMMA FIXED
                  | COMMA FIXED_TYPE
                  | '''

    if len(p) > 1:
        p[0] = p[2]


def p_object_itmes(p):
    '''object_items : object_items object_line NEWLINE
                    | object_items implicit_object
                    | member_def NEWLINE object_items
                    | object_line NEWLINE'''
    if len(p) < 4:
        if '\n' in p[2]:
            p[0] = [p[1]]
        else:
            p[1][-1].value = p[2]
            p[0] = p[1]
    else:
        if isinstance(p[2], str):
            p[0] = p[3]
        else:
            p[0] = p[1]
            p[0].append(p[2])


def p_members(p):
    ''' member_def : HEADER MEMBERS
                   | HEADER PROPERTIES'''


def p_implicit_object(p):
    '''implicit_object : INDENT object_items DEDENT'''
    p[0] = refract.Object(content=p[2])


def p_object_line(p):
    '''object_line : DASH TEXT
                   | DASH TEXT type_def
                   | DASH TEXT DASH TEXT
                   | DASH TEXT type_def DASH TEXT
                   | PLUS TEXT
                   | PLUS TEXT type_def
                   | PLUS TEXT DASH TEXT
                   | PLUS TEXT type_def DASH TEXT'''

    attributes = refract.Attributes()
    if len(p) < 4:
        p[0] = refract.Member(
            key=refract.String(content=p[2].strip()),
            value=refract.String(),
            attributes=attributes)
    else:
        try:
            attributes['typeAttributes'] = p[3].__dict__['apyb']
        except (AttributeError, KeyError):
            pass
        if p[3] is '-':
            p[0] = refract.Member(
                key=refract.String(content=p[2].strip()),
                value=refract.String(),
                meta=refract.Metadata(description=p[4]),
                attributes=attributes)
        else:
            if len(p) > 5:
                p[0] = refract.Member(
                    key=refract.String(content=p[2].strip()),
                    value=p[3],
                    meta=refract.Metadata(description=refract.String(
                        content=p[5].strip())),
                    attributes=attributes)
            else:
                p[0] = refract.Member(
                    key=refract.String(content=p[2].strip()),
                    value=p[3],
                    attributes=attributes)


def main():

    if len(sys.argv) < 2:
        sys.exit(1)

    apibParser = yacc.yacc()
    res = None
    with open(sys.argv[1]) as f:
        content = f.read()
        print(content)
        res = apibParser.parse(input=content, lexer=IndentLexer(), debug=True)

    print(JSONSerialiser().serialise(res, indent=2))


if __name__ == '__main__':
    main()
